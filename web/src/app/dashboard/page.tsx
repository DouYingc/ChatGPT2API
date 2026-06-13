"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  Image as ImageIcon,
  LoaderCircle,
  Percent,
  RefreshCw,
  Ticket,
  UserPlus,
  WalletCards,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fetchAdminOverview, type AdminOverview } from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";

type MetricCardProps = {
  label: string;
  value: string | number;
  hint?: string;
  icon: typeof Activity;
  tone?: "stone" | "emerald" | "rose" | "sky" | "amber";
  href?: string;
};

const toneClassName = {
  stone: "border-stone-200 bg-white text-stone-900",
  emerald: "border-emerald-200 bg-emerald-50 text-emerald-900",
  rose: "border-rose-200 bg-rose-50 text-rose-900",
  sky: "border-sky-200 bg-sky-50 text-sky-900",
  amber: "border-amber-200 bg-amber-50 text-amber-900",
};

function formatNumber(value: unknown) {
  const numberValue = Number(value || 0);
  if (!Number.isFinite(numberValue)) return "0";
  return new Intl.NumberFormat("zh-CN").format(numberValue);
}

function formatRate(value: unknown) {
  const numberValue = Number(value || 0);
  if (!Number.isFinite(numberValue)) return "0%";
  return `${Number.isInteger(numberValue) ? numberValue.toFixed(0) : numberValue.toFixed(1)}%`;
}

function formatDuration(value: unknown) {
  const ms = Number(value || 0);
  if (!Number.isFinite(ms) || ms <= 0) return "-";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function routeLabel(value: unknown) {
  const route = String(value || "").toLowerCase();
  if (route === "pool") return "号池";
  if (route === "relay") return "中转";
  return "未知";
}

function resolutionLabel(value: unknown) {
  const text = String(value || "").trim();
  return text ? text.toUpperCase() : "未知";
}

function MetricCard({ label, value, hint, icon: Icon, tone = "stone", href }: MetricCardProps) {
  const content = (
    <div className={`rounded-2xl border p-4 shadow-sm ${toneClassName[tone]}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[12px] font-medium text-stone-500">{label}</div>
          <div className="mt-2 font-data text-[28px] font-semibold leading-none tracking-normal text-stone-950">
            {value}
          </div>
        </div>
        <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-white/80 ring-1 ring-black/5">
          <Icon className="size-4 text-stone-600" />
        </div>
      </div>
      {hint ? <div className="mt-3 truncate text-[12px] text-stone-500">{hint}</div> : null}
    </div>
  );
  if (!href) return content;
  return (
    <Link href={href} className="block transition hover:-translate-y-0.5 hover:shadow-sm">
      {content}
    </Link>
  );
}

function buildHref(path: string, params: Record<string, string>) {
  const search = new URLSearchParams(params);
  return `${path}?${search.toString()}`;
}

function DashboardContent() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const loadOverview = async (silent = false) => {
    if (!silent) setIsLoading(true);
    try {
      const data = await fetchAdminOverview();
      setOverview(data);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载概览失败");
    } finally {
      if (!silent) setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadOverview();
  }, []);

  return (
    <section className="mt-4 space-y-5 pb-12 sm:mt-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">Overview</div>
          <h1 className="text-2xl font-semibold tracking-tight">管理员概览</h1>
          <p className="text-sm text-stone-500">
            {overview?.date ? `${overview.date} 的运营数据` : "今日运营数据"}
          </p>
        </div>
        <Button
          type="button"
          onClick={() => void loadOverview()}
          disabled={isLoading}
          className="h-10 w-fit rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800"
        >
          {isLoading ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
          刷新
        </Button>
      </div>

      {isLoading && !overview ? (
        <div className="flex min-h-[36vh] items-center justify-center">
          <LoaderCircle className="size-5 animate-spin text-stone-400" />
        </div>
      ) : overview ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <MetricCard
              label="今日生图请求"
              value={formatNumber(overview.image.total)}
              hint={`成功 ${formatNumber(overview.image.success)} 次`}
              icon={ImageIcon}
              tone="sky"
              href={buildHref("/logs", { type: "call", kind: "image", date: overview.date })}
            />
            <MetricCard
              label="失败数"
              value={formatNumber(overview.image.failed)}
              hint={overview.image.failed > 0 ? "优先看下方最近失败" : "今日暂无失败"}
              icon={XCircle}
              tone={overview.image.failed > 0 ? "rose" : "emerald"}
              href={buildHref("/logs", { type: "call", kind: "image", status: "failed", date: overview.date })}
            />
            <MetricCard
              label="接口成功率"
              value={overview.image.total > 0 ? formatRate(overview.image.success_rate) : "-"}
              hint={overview.image.total > 0 ? `平均耗时 ${formatDuration(overview.image.avg_duration_ms)}` : "今日暂无请求"}
              icon={Percent}
              tone="emerald"
              href={buildHref("/logs", { type: "call", kind: "image", status: "success", date: overview.date })}
            />
            <MetricCard
              label="新注册用户"
              value={formatNumber(overview.users.new)}
              hint={`用户总数 ${formatNumber(overview.users.total)}`}
              icon={UserPlus}
              href="/keys?created=today"
            />
            <MetricCard
              label="兑换额度"
              value={formatNumber(overview.quota.redeemed)}
              hint="用户兑换码到账额度"
              icon={Ticket}
              tone="amber"
              href="/keys"
            />
            <MetricCard
              label="消耗额度"
              value={formatNumber(overview.quota.consumed)}
              hint={`失败返还 ${formatNumber(overview.quota.refunded)}`}
              icon={WalletCards}
              href={buildHref("/logs", { type: "call", kind: "image", date: overview.date })}
            />
          </div>

          <div className="overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm">
            <div className="flex items-center justify-between gap-3 border-b border-stone-100 px-5 py-4">
              <div>
                <h2 className="text-sm font-semibold text-stone-950">最近失败记录</h2>
                <p className="mt-1 text-xs text-stone-500">只展示今日生图相关失败，方便快速判断接口状态。</p>
              </div>
              <Badge variant={overview.recent_failures.length > 0 ? "danger" : "success"} className="rounded-md">
                {overview.recent_failures.length > 0 ? `${overview.recent_failures.length} 条` : "正常"}
              </Badge>
            </div>
            <div className="overflow-x-auto">
              <Table className="min-w-[920px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>时间</TableHead>
                    <TableHead>用户</TableHead>
                    <TableHead>清晰度</TableHead>
                    <TableHead>渠道</TableHead>
                    <TableHead>耗时</TableHead>
                    <TableHead>错误</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {overview.recent_failures.map((item) => (
                    <TableRow key={item.id || `${item.time}-${item.error}`} className="text-stone-600">
                      <TableCell className="whitespace-nowrap font-data text-[12px]">{item.time || "-"}</TableCell>
                      <TableCell>{item.key_name || "-"}</TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="rounded-md bg-sky-50 text-sky-700">
                          {resolutionLabel(item.resolution)}
                        </Badge>
                      </TableCell>
                      <TableCell>{routeLabel(item.image_route)}</TableCell>
                      <TableCell>{formatDuration(item.duration_ms)}</TableCell>
                      <TableCell className="max-w-[420px] truncate text-stone-500">{item.error || item.summary || "-"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {overview.recent_failures.length === 0 ? (
              <div className="px-6 py-10 text-center text-sm text-stone-500">今日暂无失败记录</div>
            ) : null}
          </div>
        </>
      ) : null}
    </section>
  );
}

export default function DashboardPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <DashboardContent />;
}
