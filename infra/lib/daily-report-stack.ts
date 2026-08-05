import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as iam from "aws-cdk-lib/aws-iam";
import * as ecr_assets from "aws-cdk-lib/aws-ecr-assets";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import * as cdk from "aws-cdk-lib/core";
import type { Construct } from "constructs";
import * as path from "path";

const DOMAIN_NAME = "nippou.msg-network.app";

export interface DailyReportStackProps extends cdk.StackProps {
	certificate: acm.ICertificate;
}

export class DailyReportStack extends cdk.Stack {
	constructor(scope: Construct, id: string, props: DailyReportStackProps) {
		super(scope, id, props);

		// ========================================
		// S3: テンプレート docx 保管用
		// ========================================
		const templateBucket = new s3.Bucket(this, "TemplateBucket", {
			removalPolicy: cdk.RemovalPolicy.RETAIN,
			blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
		});

		// テンプレートファイルをデプロイ
		new s3deploy.BucketDeployment(this, "DeployTemplate", {
			sources: [
				s3deploy.Source.asset(path.join(__dirname, "../../backend/templates")),
			],
			destinationBucket: templateBucket,
			destinationKeyPrefix: "templates",
		});

		// ========================================
		// Lambda: Docker イメージベース
		// ========================================
		const backendFunction = new lambda.DockerImageFunction(
			this,
			"BackendFunction",
			{
				code: lambda.DockerImageCode.fromImageAsset(
					path.join(__dirname, "../../backend"),
					{
						file: "Dockerfile.lambda",
						platform: ecr_assets.Platform.LINUX_ARM64,
					},
				),
				architecture: lambda.Architecture.ARM_64,
				memorySize: 512,
				// GitHub API 13 repo × 数百 ms + Bedrock + Calendar 全部直列で 30s では危ういので 60s
				timeout: cdk.Duration.seconds(60),
				environment: {
					AWS_REGION_NAME: this.region,
					BEDROCK_MODEL_ID: "global.anthropic.claude-sonnet-5",
					TEMPLATE_BUCKET: templateBucket.bucketName,
					TEMPLATE_KEY: "templates/業務日報テンプレート.docx",
				},
			},
		);

		// Lambda に Bedrock 呼び出し権限を付与
		backendFunction.addToRolePolicy(
			new iam.PolicyStatement({
				actions: ["bedrock:InvokeModel"],
				resources: ["*"],
			}),
		);

		// Lambda に S3 読み取り権限を付与
		templateBucket.grantRead(backendFunction);

		// Lambda に Secrets Manager 読み取り権限を付与
		// (daily-report/github-auth と daily-report/google-oauth を対象)
		backendFunction.addToRolePolicy(
			new iam.PolicyStatement({
				actions: ["secretsmanager:GetSecretValue"],
				resources: [
					`arn:aws:secretsmanager:${this.region}:${this.account}:secret:daily-report/*`,
				],
			}),
		);

		// ========================================
		// API Gateway: REST API
		// ========================================
		const api = new apigateway.RestApi(this, "BackendApi", {
			restApiName: "DailyReportAPI",
			binaryMediaTypes: ["*/*"],
			defaultCorsPreflightOptions: {
				allowOrigins: apigateway.Cors.ALL_ORIGINS,
				allowMethods: apigateway.Cors.ALL_METHODS,
				allowHeaders: ["Content-Type", "X-Api-Token"],
			},
		});

		const apiIntegration = new apigateway.LambdaIntegration(backendFunction);

		// /api/{proxy+} で全パスを Lambda に転送
		const apiResource = api.root.addResource("api");
		apiResource.addProxy({
			defaultIntegration: apiIntegration,
			anyMethod: true,
		});

		// ========================================
		// S3: フロントエンド静的ホスティング
		// ========================================
		const frontendBucket = new s3.Bucket(this, "FrontendBucket", {
			removalPolicy: cdk.RemovalPolicy.DESTROY,
			autoDeleteObjects: true,
			blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
		});

		// ========================================
		// CloudFront: 統合ディストリビューション
		// ========================================
		// Next.js 静的エクスポートは /personal → personal.html を生成するため、
		// 拡張子なし URI を .html に書き換える（S3 REST オリジンはディレクトリ解決しない）
		const htmlRewriteFunction = new cloudfront.Function(
			this,
			"HtmlRewriteFunction",
			{
				runtime: cloudfront.FunctionRuntime.JS_2_0,
				code: cloudfront.FunctionCode.fromInline(
					[
						"function handler(event) {",
						"  var request = event.request;",
						"  var uri = request.uri;",
						"  if (uri !== '/' && !uri.includes('.')) {",
						"    request.uri = uri.replace(/\\/+$/, '') + '.html';",
						"  }",
						"  return request;",
						"}",
					].join("\n"),
				),
			},
		);

		const distribution = new cloudfront.Distribution(this, "Distribution", {
			defaultBehavior: {
				origin: origins.S3BucketOrigin.withOriginAccessControl(frontendBucket),
				viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
				cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
				functionAssociations: [
					{
						function: htmlRewriteFunction,
						eventType: cloudfront.FunctionEventType.VIEWER_REQUEST,
					},
				],
			},
			additionalBehaviors: {
				"/api/*": {
					origin: new origins.RestApiOrigin(api),
					viewerProtocolPolicy:
						cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
					cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
					allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
					originRequestPolicy:
						cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
				},
			},
			domainNames: [DOMAIN_NAME],
			certificate: props.certificate,
			defaultRootObject: "index.html",
			errorResponses: [
				{
					httpStatus: 403,
					responseHttpStatus: 200,
					responsePagePath: "/index.html",
				},
				{
					httpStatus: 404,
					responseHttpStatus: 200,
					responsePagePath: "/index.html",
				},
			],
		});

		// フロントエンドの静的ファイルをデプロイ
		new s3deploy.BucketDeployment(this, "DeployFrontend", {
			sources: [
				s3deploy.Source.asset(path.join(__dirname, "../../frontend/out")),
			],
			destinationBucket: frontendBucket,
			distribution,
			distributionPaths: ["/*"],
		});

		// ========================================
		// Outputs
		// ========================================
		new cdk.CfnOutput(this, "CloudFrontURL", {
			value: `https://${distribution.distributionDomainName}`,
			description: "アプリケーション URL",
		});

		new cdk.CfnOutput(this, "ApiGatewayURL", {
			value: api.url,
			description: "API Gateway URL（直接アクセス用）",
		});
	}
}
