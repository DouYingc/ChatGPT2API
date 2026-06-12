"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  Copy,
  Eye,
  EyeOff,
  Gauge,
  Image as ImageIcon,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  MessageSquare,
  RefreshCw,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { changeMyPassword, fetchMyIdentity, type AuthIdentity } from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { cn } from "@/lib/utils";
import type { StoredAuthSession } from "@/store/auth";

type QuotaRow = {
  key: string;
  label: string;
  quota: number;
  used: number;
  remaining: number | null;
  unlimited: boolean;
  icon: typeof ImageIcon;
};

function formatDate(value?: string | null) {
  if (!value) return "暂无";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function maskKey(value: string) {
  const key = String(value || "").trim();
  if (!key) return "";
  if (key.length <= 14) return `${key.slice(0, 3)}...${key.slice(-3)}`;
  return `${key.slice(0, 7)}...${key.slice(-6)}`;
}

function buildQuotaRows(identity: AuthIdentity): QuotaRow[] {
  return [
    {
      key: "image_daily",
      label: "今日画图",
      quota: identity.image_daily_quota,
      used: identity.image_daily_used,
      remaining: identity.image_daily_remaining,
      unlimited: identity.image_daily_unlimited,
      icon: ImageIcon,
    },
    {
      key: "image_monthly",
      label: "本月画图",
      quota: identity.image_monthly_quota,
      used: identity.image_monthly_used,
      remaining: identity.image_monthly_remaining,
      unlimited: identity.image_monthly_unlimited,
      icon: ImageIcon,
    },
    {
      key: "image_total",
      label: "画图总额度",
      quota: identity.image_total_quota,
      used: identity.image_total_used,
      remaining: identity.image_total_remaining,
      unlimited: identity.image_total_unlimited,
      icon: ImageIcon,
    },
    {
      key: "chat_daily",
      label: "今日对话",
      quota: identity.chat_daily_quota,
      used: identity.chat_daily_used,
      remaining: identity.chat_daily_remaining,
      unlimited: identity.chat_daily_unlimited,
      icon: MessageSquare,
    },
    {
      key: "chat_monthly",
      label: "本月对话",
      quota: identity.chat_monthly_quota,
      used: identity.chat_monthly_used,
      remaining: identity.chat_monthly_remaining,
      unlimited: identity.chat_monthly_unlimited,
      icon: MessageSquare,
    },
    {
      key: "chat_total",
      label: "对话总额度",
      quota: identity.chat_total_quota,
      used: identity.chat_total_used,
      remaining: identity.chat_total_remaining,
      unlimited: identity.chat_total_unlimited,
      icon: MessageSquare,
    },
  ];
}

function ProfilePageContent({ session }: { session: StoredAuthSession }) {
  const [identity, setIdentity] = useState<AuthIdentity | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showKey, setShowKey] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isChangingPassword, setIsChangingPassword] = useState(false);

  const quotaRows = useMemo(() => (identity ? buildQuotaRows(identity) : []), [identity]);

  const loadIdentity = async () => {
    setIsLoading(true);
    try {
      const data = await fetchMyIdentity();
      setIdentity(data.identity);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载账户信息失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadIdentity();
  }, []);

  const handleCopyKey = async () => {
    try {
      await navigator.clipboard.writeText(session.key);
      toast.success("API Key 已复制");
    } catch {
      toast.error("复制失败");
    }
  };

  const handleChangePassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (session.role !== "user") {
      toast.error("当前登录方式不支持修改密码");
      return;
    }
    if (!currentPassword) {
      toast.error("请输入当前密码");
      return;
    }
    if (newPassword.length < 6) {
      toast.error("新密码至少需要 6 个字符");
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error("两次输入的新密码不一致");
      return;
    }
    setIsChangingPassword(true);
    try {
      const data = await changeMyPassword(currentPassword, newPassword);
      setIdentity(data.identity);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      toast.success("密码已更新");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "修改密码失败");
    } finally {
      setIsChangingPassword(false);
    }
  };

  const displayName = identity?.name || session.name || (session.role === "admin" ? "管理员" : "普通用户");
  const username = identity?.username || "";

  return (
    <div className="space-y-6 pb-12">
      <section className="mt-4 flex flex-col gap-4 sm:mt-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="font-data text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              Account · Profile
            </span>
            <span className="h-px w-8 bg-border" />
          </div>
          <h1 className="text-[26px] font-semibold tracking-tight text-foreground">账户中心</h1>
          <p className="text-[13px] text-muted-foreground">
            查看当前账号、额度、API Key，并维护自己的登录密码。
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          className="h-9 w-fit rounded-xl border-stone-200 bg-white px-4 text-stone-700"
          onClick={() => void loadIdentity()}
          disabled={isLoading}
        >
          {isLoading ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
          刷新
        </Button>
      </section>

      {isLoading && !identity ? (
        <div className="flex min-h-[30vh] items-center justify-center">
          <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[1fr_1.1fr]">
          <div className="space-y-5">
            <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
              <div className="flex items-start justify-between gap-4">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-stone-950 text-white">
                    <UserRound className="size-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="truncate text-lg font-semibold text-stone-950">{displayName}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <Badge variant={session.role === "admin" ? "violet" : "success"}>
                        {session.role === "admin" ? "管理员" : "普通用户"}
                      </Badge>
                      <Badge variant="outline">{identity?.account_tier === "premium" ? "Premium" : "Free"}</Badge>
                    </div>
                  </div>
                </div>
              </div>
              <div className="mt-5 grid gap-3 text-sm text-stone-700">
                <InfoRow label="用户名" value={username || (session.role === "admin" ? "管理员密钥" : "未设置")} />
                <InfoRow label="账号 ID" value={identity?.id || session.subjectId || "admin"} mono />
                <InfoRow label="创建时间" value={formatDate(identity?.created_at)} />
                <InfoRow label="最后使用" value={formatDate(identity?.last_used_at)} />
              </div>
            </section>

            <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
              <div className="flex items-center gap-2 text-sm font-semibold text-stone-950">
                <KeyRound className="size-4" />
                API Key
              </div>
              <div className="mt-3 rounded-xl border border-stone-200 bg-stone-50 px-3 py-2">
                <div className="break-all font-data text-[12px] leading-6 text-stone-700">
                  {showKey ? session.key : maskKey(session.key)}
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="h-9 rounded-xl border-stone-200 bg-white px-3 text-stone-700"
                  onClick={() => setShowKey((value) => !value)}
                >
                  {showKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                  {showKey ? "隐藏" : "显示"}
                </Button>
                <Button
                  type="button"
                  className="h-9 rounded-xl bg-stone-950 px-3 text-white hover:bg-stone-800"
                  onClick={() => void handleCopyKey()}
                >
                  <Copy className="size-4" />
                  复制
                </Button>
              </div>
            </section>

            <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
              <div className="flex items-center gap-2 text-sm font-semibold text-stone-950">
                <LockKeyhole className="size-4" />
                修改密码
              </div>
              {session.role === "user" ? (
                <form className="mt-4 space-y-3" onSubmit={(event) => void handleChangePassword(event)}>
                  <Input
                    type="password"
                    value={currentPassword}
                    onChange={(event) => setCurrentPassword(event.target.value)}
                    placeholder="当前密码"
                    autoComplete="current-password"
                    className="h-10 rounded-xl border-stone-200 bg-white"
                  />
                  <Input
                    type="password"
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                    placeholder="新密码"
                    autoComplete="new-password"
                    className="h-10 rounded-xl border-stone-200 bg-white"
                  />
                  <Input
                    type="password"
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    placeholder="再次输入新密码"
                    autoComplete="new-password"
                    className="h-10 rounded-xl border-stone-200 bg-white"
                  />
                  <Button
                    type="submit"
                    className="h-10 w-full rounded-xl bg-stone-950 text-white hover:bg-stone-800"
                    disabled={isChangingPassword}
                  >
                    {isChangingPassword ? <LoaderCircle className="size-4 animate-spin" /> : <ShieldCheck className="size-4" />}
                    保存新密码
                  </Button>
                </form>
              ) : (
                <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-800">
                  管理员密钥登录不使用账号密码。需要更换管理员密钥时，请修改服务器环境变量或 config.json。
                </div>
              )}
            </section>
          </div>

          <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-stone-950">
                <Gauge className="size-4" />
                额度
              </div>
              <Badge variant="outline">实时余额</Badge>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {quotaRows.map((row) => (
                <QuotaTile key={row.key} row={row} />
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function InfoRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-stone-100 bg-stone-50/70 px-3 py-2">
      <span className="shrink-0 text-xs text-stone-500">{label}</span>
      <span className={cn("min-w-0 truncate text-right text-sm font-medium text-stone-800", mono ? "font-data" : "")}>
        {value}
      </span>
    </div>
  );
}

function QuotaTile({ row }: { row: QuotaRow }) {
  const Icon = row.icon;
  const exhausted = !row.unlimited && (row.remaining ?? 0) <= 0;
  const percent = row.unlimited || row.quota <= 0
    ? 0
    : Math.max(0, Math.min(100, Math.round((row.used / row.quota) * 100)));

  return (
    <div className="rounded-xl border border-stone-100 bg-stone-50/70 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="size-4 shrink-0 text-stone-500" />
          <span className="truncate text-sm font-medium text-stone-800">{row.label}</span>
        </div>
        {row.unlimited ? (
          <span className="shrink-0 rounded-lg bg-violet-50 px-2 py-1 font-data text-[11px] font-semibold text-violet-700">
            不限
          </span>
        ) : exhausted ? (
          <span className="shrink-0 rounded-lg bg-rose-50 px-2 py-1 font-data text-[11px] font-semibold text-rose-700">
            已用完
          </span>
        ) : (
          <span className="shrink-0 font-data text-xs font-semibold text-stone-800">剩 {row.remaining}</span>
        )}
      </div>
      {!row.unlimited ? (
        <>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-stone-200">
            <span
              className={cn(
                "block h-full rounded-full",
                exhausted ? "bg-rose-500" : percent >= 80 ? "bg-amber-500" : "bg-emerald-500",
              )}
              style={{ width: `${percent}%` }}
            />
          </div>
          <div className="mt-2 font-data text-[11px] text-stone-500">
            已用 {row.used} / {row.quota}
          </div>
        </>
      ) : (
        <div className="mt-2 font-data text-[11px] text-stone-500">已用 {row.used}</div>
      )}
    </div>
  );
}

export default function ProfilePage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin", "user"]);

  if (isCheckingAuth || !session) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return <ProfilePageContent session={session} />;
}
