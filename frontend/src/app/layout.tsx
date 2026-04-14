import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

const geistSans = Geist({
	variable: "--font-geist-sans",
	subsets: ["latin"],
});

const geistMono = Geist_Mono({
	variable: "--font-geist-mono",
	subsets: ["latin"],
});

export const metadata: Metadata = {
	title: "業務日報ジェネレーター",
	description: "業務日報を自動生成するツール",
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<html lang="ja" className={`${geistSans.variable} ${geistMono.variable}`}>
			<body className="min-h-dvh bg-background text-foreground antialiased">
				{children}
				<Toaster position="bottom-right" richColors />
			</body>
		</html>
	);
}
