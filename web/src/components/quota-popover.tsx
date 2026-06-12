"use client";

import { useEffect, useState } from "react";
import {
  CalendarClock,
  CalendarDays,
  ExternalLink,
  Gauge,
  Image as ImageIcon,
  Infinity as InfinityIcon,
  LoaderCircle,
  MessageSquare,
  Ticket,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { IMAGE_QUOTA_RULES, QUOTA_SHOP_URL } from "@/lib/billing";
import { fetchMyIdentity, redeemQuotaCode, type AuthIdentity } from "@/lib/api";
import { cn } from "@/lib/utils";

type QuotaRow = {
  key:
    | "image_daily"
    | "image_monthly"
    | "image_total"
    | "chat_daily"
    | "chat_monthly"
    | "chat_total";
  label: string;
  hint: string;
  icon: typeof ImageIcon;
  quota: number;
  used: number;
  unlimited: boolean;
  remaining: number | null;
};

function buildRows(identity: AuthIdentity): QuotaRow[] {
  return [
    {
      key: "image_daily",
      label: "画图日限额",
      hint: "每日 00:00 自动重置",
      icon: ImageIcon,
      quota: identity.image_daily_quota,
      used: identity.image_daily_used,
      unlimited: identity.image_daily_unlimited,
      remaining: identity.image_daily_remaining,
    },
    {
      key: "image_monthly",
      label: "画图月限额",
      hint: "每月 1 号 00:00 自动重置",
      icon: ImageIcon,
      quota: identity.image_monthly_quota,
      used: identity.image_monthly_used,
      unlimited: identity.image_monthly_unlimited,
      remaining: identity.image_monthly_remaining,
    },
    {
      key: "image_total",
      label: "画图总额度",
      hint: "永久计数，可用兑换码增加",
      icon: ImageIcon,
      quota: identity.image_total_quota,
      used: identity.image_total_used,
      unlimited: identity.image_total_unlimited,
      remaining: identity.image_total_remaining,
    },
    {
      key: "chat_daily",
      label: "对话日限额",
      hint: "每日 00:00 自动重置",
      icon: CalendarDays,
      quota: identity.chat_daily_quota,
      used: identity.chat_daily_used,
      unlimited: identity.chat_daily_unlimited,
      remaining: identity.chat_daily_remaining,
    },
    {
      key: "chat_monthly",
      label: "对话月限额",
      hint: "每月 1 号 00:00 自动重置",
      icon: CalendarClock,
      quota: identity.chat_monthly_quota,
      used: identity.chat_monthly_used,
      unlimited: identity.chat_monthly_unlimited,
      remaining: identity.chat_monthly_remaining,
    },
    {
      key: "chat_total",
      label: "对话总额度",
      hint: "永久计数",
      icon: MessageSquare,
      quota: identity.chat_total_quota,
      used: identity.chat_total_used,
      unlimited: identity.chat_total_unlimited,
      remaining: identity.chat_total_remaining,
    },
  ];
}

export function QuotaPopover() {
  const [open, setOpen] = useState(false);
  const [identity, setIdentity] = useState<AuthIdentity | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isRedeeming, setIsRedeeming] = useState(false);
  const [redeemCode, setRedeemCode] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    let active = true;
    setIsLoading(true);
    setError("");
    fetchMyIdentity()
      .then(({ identity: data }) => {
        if (!active) return;
        setIdentity(data);
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "加载额度失败");
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [open]);

  const handleRedeem = async () => {
    const normalizedCode = redeemCode.trim();
    if (!normalizedCode) {
      toast.error("请输入兑换码");
      return;
    }
    setIsRedeeming(true);
    try {
      const data = await redeemQuotaCode(normalizedCode);
      setIdentity(data.identity);
      setRedeemCode("");
      toast.success(`兑换成功，画图总额度 +${data.amount}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "兑换失败");
    } finally {
      setIsRedeeming(false);
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="查看额度使用情况"
          title="查看额度"
          className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-border/70 bg-card px-2.5 text-[12px] font-bold leading-none text-foreground shadow-sm transition hover:border-foreground/20 hover:bg-secondary"
        >
          <Gauge className="size-3.5 shrink-0" />
          <span>额度</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={8} className="w-[320px] p-0">
        <div className="border-b border-stone-100 px-4 py-3">
          <div className="text-sm font-semibold text-stone-900">额度使用情况</div>
          <p className="mt-0.5 text-xs leading-5 text-stone-500">
            文字对话扣对话额度；画图页和对话里的生图都扣画图额度。
          </p>
          <div className="mt-2 grid grid-cols-3 gap-1.5">
            {IMAGE_QUOTA_RULES.map((rule) => (
              <div key={rule.label} className="rounded-lg border border-stone-200 bg-stone-50 px-2 py-1.5 text-center">
                <div className="font-data text-[12px] font-semibold text-stone-900">{rule.label}</div>
                <div className="mt-0.5 text-[11px] text-stone-500">扣 {rule.cost} 额度</div>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11px] leading-5 text-stone-500">
            失败任务会自动返还预扣额度。
          </p>
        </div>
        <div className="px-4 py-3">
          {isLoading ? (
            <div className="flex items-center justify-center py-6 text-stone-400">
              <LoaderCircle className="size-4 animate-spin" />
            </div>
          ) : error ? (
            <div className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div>
          ) : identity ? (
            <div className="space-y-3">
              <div className="space-y-2">
                {buildRows(identity).map((row) => (
                  <QuotaItem key={row.key} row={row} />
                ))}
              </div>
              {identity.role === "user" && !identity.image_total_unlimited ? (
                <div className="border-t border-stone-100 pt-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-xs font-medium text-stone-600">
                      <Ticket className="size-3.5" />
                      兑换画图额度
                    </div>
                    <a
                      href={QUOTA_SHOP_URL}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 rounded-md bg-stone-900 px-2 py-1 text-[11px] font-medium text-white transition hover:bg-stone-800"
                    >
                      购买
                      <ExternalLink className="size-3" />
                    </a>
                  </div>
                  <p className="mb-2 text-[11px] leading-5 text-stone-500">
                    购买额度后会获得兑换码，回到这里输入即可到账。
                  </p>
                  <div className="flex gap-2">
                    <Input
                      value={redeemCode}
                      onChange={(event) => setRedeemCode(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          void handleRedeem();
                        }
                      }}
                      placeholder="输入兑换码"
                      className="h-9 rounded-lg border-stone-200 bg-white font-data text-[12px] shadow-none"
                    />
                    <Button
                      type="button"
                      className="h-9 rounded-lg bg-stone-950 px-3 text-white hover:bg-stone-800"
                      onClick={() => void handleRedeem()}
                      disabled={isRedeeming}
                    >
                      {isRedeeming ? <LoaderCircle className="size-3.5 animate-spin" /> : null}
                      兑换
                    </Button>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function QuotaItem({ row }: { row: QuotaRow }) {
  const Icon = row.icon;
  const exhausted = !row.unlimited && (row.remaining ?? 0) <= 0;
  const percent = row.unlimited || row.quota <= 0
    ? 0
    : Math.max(0, Math.min(100, Math.round((row.used / row.quota) * 100)));
  return (
    <div className="rounded-lg border border-stone-100 bg-stone-50/60 px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="size-3.5 shrink-0 text-stone-500" />
          <div className="min-w-0">
            <div className="text-[13px] font-medium leading-tight text-stone-800">{row.label}</div>
            <div className="mt-0.5 truncate text-[11px] leading-tight text-stone-500">{row.hint}</div>
          </div>
        </div>
        <div className="shrink-0 text-right">
          {row.unlimited ? (
            <span className="inline-flex items-center gap-1 rounded-md bg-violet-50 px-1.5 py-0.5 font-data text-[11px] font-medium text-violet-700">
              <InfinityIcon className="size-3" />
              不限
            </span>
          ) : exhausted ? (
            <span className="rounded-md bg-rose-50 px-1.5 py-0.5 font-data text-[11px] font-medium text-rose-700">
              已用完
            </span>
          ) : (
            <span className="font-data tabular-nums text-[12px] font-semibold text-stone-800">
              剩 {row.remaining}
            </span>
          )}
        </div>
      </div>
      {!row.unlimited ? (
        <>
          <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-stone-200/70">
            <span
              className={cn(
                "block h-full rounded-full transition-all",
                exhausted ? "bg-rose-500" : percent >= 80 ? "bg-amber-500" : "bg-emerald-500",
              )}
              style={{ width: `${Math.min(100, percent)}%` }}
            />
          </div>
          <div className="mt-1 font-data tabular-nums text-[11px] text-stone-500">
            已用 {row.used} / {row.quota}
          </div>
        </>
      ) : (
        <div className="mt-1.5 font-data tabular-nums text-[11px] text-stone-500">
          已用 {row.used}
        </div>
      )}
    </div>
  );
}
