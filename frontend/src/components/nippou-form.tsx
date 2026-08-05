"use client";

import {
	Download,
	GitCommit,
	Loader2,
	Mic,
	MicOff,
	Sparkles,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
	type CalendarEvent,
	fromCommits,
	generateDocx,
	parseWorkContent,
	type ShiftPattern,
	type Slots,
} from "@/lib/api";

const SHIFT_OPTIONS = {
	normal: {
		label: "早番勤務 (9〜17時)",
		hours: [9, 10, 11, 12, 13, 14, 15, 16, 17],
	},
	late: {
		label: "通常勤務 (13〜21時)",
		hours: [13, 14, 15, 16, 17, 18, 19, 20, 21],
	},
} as const;

function getTodayString(): string {
	const now = new Date();
	const y = now.getFullYear();
	const m = String(now.getMonth() + 1).padStart(2, "0");
	const d = String(now.getDate()).padStart(2, "0");
	return `${y}-${m}-${d}`;
}

export function NippouForm({
	enableFromCommits = false,
}: {
	enableFromCommits?: boolean;
}) {
	const [date, setDate] = useState(getTodayString());
	const [shiftPattern, setShiftPattern] = useState<ShiftPattern>("late");
	const [department, setDepartment] = useState("");
	const [userName, setUserName] = useState("");
	const [notes, setNotes] = useState("");
	const [text, setText] = useState("");
	const [slots, setSlots] = useState<Slots | null>(null);
	const [loading, setLoading] = useState(false);
	const [generating, setGenerating] = useState(false);
	const [importing, setImporting] = useState(false);
	const [apiToken, setApiToken] = useState("");
	const [importInfo, setImportInfo] = useState<{
		commitsSummary: string;
		calendarEvents: CalendarEvent[];
	} | null>(null);
	const [error, setError] = useState("");
	const [isListening, setIsListening] = useState(false);
	const recognitionRef = useRef<SpeechRecognition | null>(null);
	const shouldListenRef = useRef(false);

	// localStorage から所属・氏名を復元
	useEffect(() => {
		const saved = localStorage.getItem("nippou-profile");
		if (saved) {
			const profile = JSON.parse(saved);
			setDepartment(profile.department || "");
			setUserName(profile.name || "");
		}
	}, []);

	// 所属・氏名が変わったら localStorage に保存
	useEffect(() => {
		if (department || userName) {
			localStorage.setItem(
				"nippou-profile",
				JSON.stringify({ department, name: userName }),
			);
		}
	}, [department, userName]);

	// API トークンを localStorage と同期（個人ページのみ）
	useEffect(() => {
		if (!enableFromCommits) return;
		const saved = localStorage.getItem("nippou-api-token");
		if (saved) setApiToken(saved);
	}, [enableFromCommits]);

	useEffect(() => {
		if (!enableFromCommits) return;
		if (apiToken) {
			localStorage.setItem("nippou-api-token", apiToken);
		}
	}, [apiToken, enableFromCommits]);

	// --- 音声入力 ---
	const toggleListening = () => {
		if (isListening) {
			shouldListenRef.current = false;
			recognitionRef.current?.stop();
			setIsListening(false);
			return;
		}

		const SpeechRecognition =
			window.SpeechRecognition || window.webkitSpeechRecognition;
		if (!SpeechRecognition) {
			setError("このブラウザは音声入力に対応していません（Chrome推奨）");
			return;
		}

		shouldListenRef.current = true;

		let processedCount = 0;

		const startRecognition = () => {
			const recognition = new SpeechRecognition();
			recognition.lang = "ja-JP";
			recognition.interimResults = false;
			recognition.continuous = true;

			recognition.onresult = (event: SpeechRecognitionEvent) => {
				for (let i = processedCount; i < event.results.length; i++) {
					if (event.results[i].isFinal) {
						const transcript = event.results[i][0].transcript;
						setText((prev) => (prev ? `${prev}${transcript}` : transcript));
						processedCount = i + 1;
					}
				}
			};

			recognition.onerror = (event: Event) => {
				const errorEvent = event as Event & { error?: string };
				const errorMessages: Record<string, string> = {
					"not-allowed":
						"マイクへのアクセスが許可されていません。ブラウザの設定を確認してください。",
					"service-not-available": "音声認識サービスが利用できません。",
					network:
						"音声認識サーバーに接続できません。Chrome ブラウザで開き直してください。",
					"no-speech": "音声が検出されませんでした。",
				};
				const msg = errorMessages[errorEvent.error ?? ""];
				if (msg) {
					shouldListenRef.current = false;
					setIsListening(false);
					setError(msg);
				}
			};

			recognition.onend = () => {
				if (shouldListenRef.current) {
					startRecognition();
				} else {
					setIsListening(false);
				}
			};

			recognitionRef.current = recognition;
			recognition.start();
		};

		startRecognition();
		setIsListening(true);
	};

	// --- コミット履歴から自動生成 ---
	const handleFromCommits = async () => {
		if (!apiToken.trim()) {
			setError("アクセストークンを入力してください");
			return;
		}
		setError("");
		setImporting(true);
		try {
			const result = await fromCommits(
				{ date, shift_pattern: shiftPattern },
				apiToken.trim(),
			);
			setSlots(result.slots);
			setImportInfo({
				commitsSummary: result.commits_summary,
				calendarEvents: result.calendar_events,
			});
			toast.success(
				result.calendar_events.length > 0
					? `コミット履歴＋予定${result.calendar_events.length}件から生成しました`
					: "コミット履歴から生成しました",
			);
		} catch (e) {
			setError(e instanceof Error ? e.message : "エラーが発生しました");
		} finally {
			setImporting(false);
		}
	};

	// --- AI 変換 ---
	const handleParse = async () => {
		if (!text.trim()) {
			setError("業務内容を入力してください");
			return;
		}
		setError("");
		setLoading(true);
		try {
			const result = await parseWorkContent({
				date,
				shift_pattern: shiftPattern,
				text,
			});
			setSlots(result.slots);
		} catch (e) {
			setError(e instanceof Error ? e.message : "エラーが発生しました");
		} finally {
			setLoading(false);
		}
	};

	// --- スロット編集 ---
	const handleSlotChange = (hour: string, value: string) => {
		if (!slots) return;
		setSlots({ ...slots, [hour]: value || null });
	};

	// --- Word 生成 ---
	const handleGenerate = async () => {
		if (!slots) return;
		setGenerating(true);
		setError("");
		try {
			const blob = await generateDocx({
				date,
				shift_pattern: shiftPattern,
				slots,
				department,
				name: userName,
				notes,
			});
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			const [y, m, d] = date.split("-");
			a.href = url;
			a.download = `業務日報_${y}_${m}_${d}.docx`;
			a.click();
			URL.revokeObjectURL(url);
			toast.success("Word ファイルをダウンロードしました");
		} catch (e) {
			setError(e instanceof Error ? e.message : "エラーが発生しました");
		} finally {
			setGenerating(false);
		}
	};

	const hours = SHIFT_OPTIONS[shiftPattern].hours;

	return (
		<main className="mx-auto max-w-2xl px-4 py-8">
			<div className="mb-8 text-center">
				<h1 className="text-2xl font-bold tracking-tight">
					業務日報ジェネレーター
				</h1>
				<p className="mt-1 text-sm text-muted-foreground">
					業務内容を入力するだけで、Word ファイルを自動生成します
				</p>
			</div>

			<div className="space-y-6">
				{/* 日付 & 勤務パターン */}
				<Card>
					<CardHeader>
						<CardTitle className="text-base">基本情報</CardTitle>
					</CardHeader>
					<CardContent className="space-y-4">
						<div className="grid grid-cols-2 gap-4">
							<div className="space-y-2">
								<Label htmlFor="department">所属</Label>
								<Input
									id="department"
									value={department}
									onChange={(e) => setDepartment(e.target.value)}
									placeholder="例: デジタルマーケティング部"
								/>
							</div>
							<div className="space-y-2">
								<Label htmlFor="userName">氏名</Label>
								<Input
									id="userName"
									value={userName}
									onChange={(e) => setUserName(e.target.value)}
									placeholder="例: 山田　太郎"
								/>
							</div>
						</div>
						<div className="grid grid-cols-2 gap-4">
							<div className="space-y-2">
								<Label htmlFor="date">日付</Label>
								<Input
									id="date"
									type="date"
									value={date}
									onChange={(e) => setDate(e.target.value)}
								/>
							</div>
							<div className="space-y-2">
								<Label>勤務パターン</Label>
								<Select
									value={shiftPattern}
									onValueChange={(v) => {
										if (v) {
											setShiftPattern(v as ShiftPattern);
											setSlots(null);
										}
									}}
								>
									<SelectTrigger className="w-full">
										<SelectValue>
											{SHIFT_OPTIONS[shiftPattern].label}
										</SelectValue>
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="late">
											{SHIFT_OPTIONS.late.label}
										</SelectItem>
										<SelectItem value="normal">
											{SHIFT_OPTIONS.normal.label}
										</SelectItem>
									</SelectContent>
								</Select>
							</div>
						</div>
						<p className="text-xs text-muted-foreground">
							所属・氏名はブラウザに保存され、次回以降自動で入力されます
						</p>
					</CardContent>
				</Card>

				{/* コミット履歴から自動生成（個人ページのみ） */}
				{enableFromCommits && (
					<Card>
						<CardHeader>
							<CardTitle className="text-base">
								コミット履歴から自動生成
							</CardTitle>
							<CardDescription>
								指定日の GitHub コミットと Google Calendar
								を突き合わせて、日報のたたき台を作成します。
							</CardDescription>
						</CardHeader>
						<CardContent className="space-y-3">
							<div className="space-y-2">
								<Label htmlFor="apiToken">アクセストークン</Label>
								<Input
									id="apiToken"
									type="password"
									value={apiToken}
									onChange={(e) => setApiToken(e.target.value)}
									placeholder="共有されたトークンを入力"
								/>
								<p className="text-xs text-muted-foreground">
									ブラウザに保存され、次回以降自動で入力されます
								</p>
							</div>
							<Button
								onClick={handleFromCommits}
								disabled={importing}
								className="w-full"
							>
								{importing ? (
									<>
										<Loader2 className="h-4 w-4 animate-spin" />
										取得中...
									</>
								) : (
									<>
										<GitCommit className="h-4 w-4" />
										コミット履歴から日報を生成
									</>
								)}
							</Button>
							{importInfo && (
								<div className="space-y-2 rounded-lg border bg-muted/30 px-3 py-2 text-xs">
									<div className="flex items-center gap-2">
										<span
											className={`inline-flex items-center rounded-full px-2 py-0.5 font-medium ${
												importInfo.calendarEvents.length > 0
													? "bg-blue-100 text-blue-700"
													: "bg-slate-100 text-slate-600"
											}`}
										>
											{importInfo.calendarEvents.length > 0
												? `予定 ${importInfo.calendarEvents.length} 件`
												: "予定なし"}
										</span>
									</div>
									{importInfo.calendarEvents.length > 0 && (
										<ul className="space-y-0.5 text-muted-foreground">
											{importInfo.calendarEvents.map((ev) => (
												<li key={`${ev.start}-${ev.title}`}>
													{ev.start.slice(11, 16)}〜{ev.end.slice(11, 16)}{" "}
													{ev.title}
												</li>
											))}
										</ul>
									)}
									<details>
										<summary className="cursor-pointer text-muted-foreground">
											取得したコミット履歴を確認
										</summary>
										<pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-xs">
											{importInfo.commitsSummary}
										</pre>
									</details>
								</div>
							)}
						</CardContent>
					</Card>
				)}

				{/* テキスト入力 */}
				<Card>
					<CardHeader>
						<CardTitle className="text-base">
							業務内容（手動入力・音声入力）
						</CardTitle>
						<CardDescription>
							{enableFromCommits
								? "コミット履歴で足りないときや、コミットが無い日はこちらを使ってください（Chrome推奨）。"
								: "自然言語で入力してください。音声入力も使えます（Chrome推奨）。"}
						</CardDescription>
					</CardHeader>
					<CardContent className="space-y-4">
						<Textarea
							value={text}
							onChange={(e) => setText(e.target.value)}
							placeholder="例: 9時からメールチェック、10時からMSGアプリの開発、12時に昼休憩..."
							rows={5}
							className="resize-none"
						/>
						<div className="flex gap-3">
							<Button
								variant="outline"
								onClick={toggleListening}
								className={isListening ? "border-red-500 text-red-500" : ""}
							>
								{isListening ? (
									<>
										<MicOff className="h-4 w-4" />
										録音停止
									</>
								) : (
									<>
										<Mic className="h-4 w-4" />
										音声入力
									</>
								)}
							</Button>
							<Button
								onClick={handleParse}
								disabled={loading}
								className="flex-1"
							>
								{loading ? (
									<>
										<Loader2 className="h-4 w-4 animate-spin" />
										解析中...
									</>
								) : (
									<>
										<Sparkles className="h-4 w-4" />
										AI でスロットに変換
									</>
								)}
							</Button>
						</div>
					</CardContent>
				</Card>

				{/* エラー表示 */}
				{error && (
					<div className="rounded-lg border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
						{error}
					</div>
				)}

				{/* スロット編集 */}
				{slots && (
					<Card>
						<CardHeader>
							<CardTitle className="text-base">スロット確認・編集</CardTitle>
							<CardDescription>
								変換結果を確認し、必要に応じて修正してください（各20文字以内）
							</CardDescription>
						</CardHeader>
						<CardContent>
							<div className="divide-y rounded-lg border">
								{hours.map((hour) => {
									const key = String(hour);
									const value = slots[key];
									return (
										<div key={key} className="flex items-center">
											<div className="w-16 shrink-0 border-r bg-muted px-3 py-2.5 text-center text-sm font-medium">
												{hour}時
											</div>
											<Input
												value={value || ""}
												onChange={(e) => handleSlotChange(key, e.target.value)}
												placeholder="—"
												maxLength={20}
												className="rounded-none border-0 shadow-none focus-visible:ring-0"
											/>
										</div>
									);
								})}
							</div>
						</CardContent>
					</Card>
				)}

				{/* 特記事項 */}
				{slots && (
					<Card>
						<CardHeader>
							<CardTitle className="text-base">特記事項</CardTitle>
							<CardDescription>任意。空欄のままでもOKです。</CardDescription>
						</CardHeader>
						<CardContent>
							<Textarea
								value={notes}
								onChange={(e) => setNotes(e.target.value)}
								placeholder="特記事項があれば入力..."
								rows={3}
								className="resize-none"
							/>
						</CardContent>
					</Card>
				)}

				{/* Word 生成ボタン */}
				{slots && (
					<Button
						onClick={handleGenerate}
						disabled={generating}
						size="lg"
						className="w-full"
					>
						{generating ? (
							<>
								<Loader2 className="h-4 w-4 animate-spin" />
								生成中...
							</>
						) : (
							<>
								<Download className="h-4 w-4" />
								Word ファイルを生成・ダウンロード
							</>
						)}
					</Button>
				)}
			</div>
		</main>
	);
}
