"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Image as ImageIcon,
  LoaderCircle,
  Mail,
  Percent,
  RefreshCw,
  Server,
  Ticket,
  UserPlus,
  WalletCards,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fetchAdminOverview, runRegisterHealthCheck, type AdminOverview, type RegisterHealthResult } from "@/lib/api";
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

function healthLevel(item: RegisterHealthResult["checks"][number]) {
  const level = String(item.level || "").toLowerCase();
  if (level === "warning") return "warning";
  if (level === "error") return "error";
  return item.ok ? "ok" : "error";
}

function healthLabel(item: RegisterHealthResult["checks"][number]) {
  const level = healthLevel(item);
  if (level === "warning") return "参考";
  if (level === "error") return "异常";
  return "正常";
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
  const [registerHealth, setRegisterHealth] = useState<RegisterHealthResult | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isCheckingRegister, setIsCheckingRegister] = useState(false);

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

  const runRegisterCheck = async () => {
    setIsCheckingRegister(true);
    try {
      const data = await runRegisterHealthCheck();
      setRegisterHealth(data);
      if (data.ok) {
        const hasWarning = data.checks.some((item) => healthLevel(item) === "warning");
        toast.success(hasWarning ? "核心注册链路可用，存在参考项警告" : "注册环境检测通过");
      } else {
        toast.error("核心注册链路存在异常");
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "注册环境检测失败");
    } finally {
      setIsCheckingRegister(false);
    }
  };

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

          <div className="grid gap-4 xl:grid-cols-2">
            <div className="overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-100 px-5 py-4">
                <div>
                  <h2 className="text-sm font-semibold text-stone-950">注册环境检测</h2>
                  <p className="mt-1 text-xs text-stone-500">检测邮箱、OpenAI 注册入口与参考访问项。</p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="h-9 rounded-xl border-stone-200 bg-white px-4 text-stone-700 hover:bg-stone-50"
                  onClick={() => void runRegisterCheck()}
                  disabled={isCheckingRegister}
                >
                  {isCheckingRegister ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                  运行检测
                </Button>
              </div>
              <div className="space-y-3 p-5">
                <div className="flex flex-wrap items-center gap-2 text-sm text-stone-600">
                  <Server className="size-4 text-stone-400" />
                  <span>代理：{registerHealth?.proxy.proxy || "未检测"}</span>
                  {registerHealth?.proxy.node ? (
                    <Badge variant="secondary" className="rounded-md bg-sky-50 text-sky-700">
                      {registerHealth.proxy.node}
                    </Badge>
                  ) : null}
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {(registerHealth?.checks ?? []).map((item) => (
                    <div key={item.name} className="rounded-xl border border-stone-100 bg-stone-50/70 p-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-2 text-sm font-medium text-stone-800">
                          {healthLevel(item) === "ok" ? (
                            <CheckCircle2 className="size-4 text-emerald-600" />
                          ) : healthLevel(item) === "warning" ? (
                            <AlertCircle className="size-4 text-amber-600" />
                          ) : (
                            <AlertCircle className="size-4 text-rose-600" />
                          )}
                          <span className="truncate">{item.name}</span>
                        </div>
                        <Badge
                          variant={healthLevel(item) === "ok" ? "success" : healthLevel(item) === "warning" ? "warning" : "danger"}
                          className="rounded-md"
                        >
                          {healthLabel(item)}
                        </Badge>
                      </div>
                      <div className="mt-2 truncate text-xs text-stone-500">
                        HTTP {item.status ?? 0} · {formatDuration(item.latency_ms)}
                        {item.error ? ` · ${item.error}` : item.detail ? ` · ${item.detail}` : ""}
                      </div>
                    </div>
                  ))}
                  {!registerHealth ? (
                    <div className="col-span-full rounded-xl border border-dashed border-stone-200 px-4 py-8 text-center text-sm text-stone-500">
                      点击运行检测后显示结果
                    </div>
                  ) : null}
                </div>
              </div>
            </div>

            <div className="overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm">
              <div className="border-b border-stone-100 px-5 py-4">
                <h2 className="text-sm font-semibold text-stone-950">中转接口与号池健康</h2>
                <p className="mt-1 text-xs text-stone-500">聚合 Duck / 中转接口、号池账号和图片任务队列状态。</p>
              </div>
              <div className="grid gap-3 p-5 sm:grid-cols-2">
                <MetricCard
                  label="Duck 今日成功率"
                  value={overview.relay.today_success + overview.relay.today_fail > 0 ? formatRate(overview.relay.today_success_rate) : "-"}
                  hint={`成功 ${formatNumber(overview.relay.today_success)} · 失败 ${formatNumber(overview.relay.today_fail)} · 平均 ${formatDuration(overview.relay.today_avg_duration_ms)}`}
                  icon={Percent}
                  tone={overview.relay.today_fail > 0 ? "amber" : "emerald"}
                />
                <MetricCard
                  label="号池可用账号"
                  value={formatNumber(overview.account_pool.available)}
                  hint={`限流 ${formatNumber(overview.account_pool.limited)} · 异常 ${formatNumber(overview.account_pool.abnormal)} · 总 ${formatNumber(overview.account_pool.total)}`}
                  icon={Mail}
                  tone={overview.account_pool.available > 0 ? "emerald" : "rose"}
                />
                <MetricCard
                  label="图片队列"
                  value={formatNumber(overview.image_tasks.queued + overview.image_tasks.running)}
                  hint={`排队 ${formatNumber(overview.image_tasks.queued)} · 运行 ${formatNumber(overview.image_tasks.running)}`}
                  icon={Activity}
                  tone={overview.image_tasks.running > 0 ? "sky" : "stone"}
                />
                <MetricCard
                  label="2K/4K 并发"
                  value={`${overview.image_tasks.high_res.active}/${overview.image_tasks.high_res.limit}`}
                  hint={`高清排队 ${formatNumber(overview.image_tasks.high_res.queued)} · 运行 ${formatNumber(overview.image_tasks.high_res.running)}`}
                  icon={ImageIcon}
                  tone={overview.image_tasks.high_res.active >= overview.image_tasks.high_res.limit ? "amber" : "stone"}
                />
              </div>
              <div className="border-t border-stone-100 px-5 py-4">
                <div className="mb-2 text-xs font-medium text-stone-500">最近中转错误</div>
                {overview.relay.recent_errors.length > 0 ? (
                  <div className="space-y-2">
                    {overview.relay.recent_errors.map((item) => (
                      <div key={item.id || item.name} className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700">
                        <span className="font-medium">{item.name || "中转接口"}：</span>
                        <span>{item.error}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-xl bg-emerald-50 px-3 py-3 text-sm text-emerald-700">暂无中转错误</div>
                )}
              </div>
            </div>
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
