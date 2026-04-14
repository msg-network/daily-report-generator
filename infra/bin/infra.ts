#!/usr/bin/env node
import * as cdk from "aws-cdk-lib/core";
import { CertificateStack } from "../lib/certificate-stack";
import { DailyReportStack } from "../lib/daily-report-stack";

const app = new cdk.App();

const account = process.env.CDK_DEFAULT_ACCOUNT;

// ACM 証明書は us-east-1 で作成（CloudFront の要件）
const certStack = new CertificateStack(app, "DailyReportCertStack", {
  crossRegionReferences: true,
  env: { account, region: "us-east-1" },
  domainName: "nippou.msg-network.app",
});

// メインスタックは ap-northeast-1
const mainStack = new DailyReportStack(app, "DailyReportStack", {
  crossRegionReferences: true,
  env: { account, region: "ap-northeast-1" },
  certificate: certStack.certificate,
});

mainStack.addDependency(certStack);
