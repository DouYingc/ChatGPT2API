"use client";

import { useEffect, useMemo, useState } from "react";
import { Coins, LoaderCircle, RefreshCcw } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { fetchQuotaLedger, type QuotaLedgerEntry } from "@/lib/api";

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

const ACTION_LABELS: Record<string, string> = {
  register_grant: "注册赠送",
  redeem: "兑换码",
  image_consume: "生图扣费",
  image_refund: "失败返还",
  chat_consume: "对话扣费",
  chat_refund: "对话返还",
};

function actionLabel(action: string) {
  return ACTION_LABELS[action] || action || "-";
}

function kindLabel(kind: string) {
  return kind === "chat" ? "对话" : "画图";
}

function remainingText(item: QuotaLedgerEntry) {
  const remaining = item.remaining || {};
  const value = item.kind === "chat" ? remaining.chat_total : remaining.image_total;
  if (value === null) return "不限";
  if (typeof value === "number") return String(value);
  return "-";
}

export function QuotaLedgerCard() {
  const [items, setItems] = useState<QuotaLedgerEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const load = async (silent = false) => {
    if (!silent) setIsLoading(true);
    try {
      const data = await fetchQuotaLedger({ limit: 200 });
      setItems(data.items);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载额度流水失败");
    } finally {
      if (!silent) setIsLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const stats = useMemo(() => {
    const income = items.filter((item) => item.amount > 0).reduce((sum, item) => sum + item.amount, 0);
    const outcome = items.filter((item) => item.amount < 0).reduce((sum, item) => sum + Math.abs(item.amount), 0);
    return { total: items.length, income, outcome };
  }, [items]);

  return (
    <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-5 p-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-stone-100">
              <Coins className="size-5 text-stone-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-tight">额度流水</h2>
              <p className="text-sm text-stone-500">
                记录注册赠送、兑换、扣费和失败返还，方便排查用户额度变化。
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Stat label="最近记录" value={stats.total} />
            <Stat label="增加" value={stats.income} />
            <Stat label="扣除" value={stats.outcome} />
            <Button
              type="button"
              variant="outline"
              className="h-9 rounded-xl border-stone-200 bg-white"
              onClick={() => void load(true)}
              disabled={isLoading}
            >
              {isLoading ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCcw className="size-4" />}
              刷新
            </Button>
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-stone-200">
          {isLoading ? (
            <div className="flex items-center justify-center py-10">
              <LoaderCircle className="size-5 animate-spin text-stone-400" />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[920px] text-left text-sm">
                <thead className="border-b border-stone-200 bg-stone-50 text-[12px] font-medium text-stone-500">
                  <tr>
                    <th className="w-36 px-4 py-2.5 font-medium">时间</th>
                    <th className="w-44 px-4 py-2.5 font-medium">用户</th>
                    <th className="w-24 px-4 py-2.5 font-medium">类型</th>
                    <th className="w-28 px-4 py-2.5 font-medium">动作</th>
                    <th className="w-24 px-4 py-2.5 font-medium">变化</th>
                    <th className="w-24 px-4 py-2.5 font-medium">剩余</th>
                    <th className="px-4 py-2.5 font-medium">说明</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id} className="border-b border-stone-100 even:bg-stone-50/40 hover:bg-stone-50">
                      <td className="px-4 py-3 font-data text-xs text-stone-500">{formatDateTime(item.created_at)}</td>
                      <td className="px-4 py-3">
                        <div className="max-w-[180px] truncate text-sm font-medium text-stone-800">
                          {item.user_name || item.user_id || "-"}
                        </div>
                        <div className="font-data text-[11px] text-stone-400">{item.user_id}</div>
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant="secondary" className="rounded-md">
                          {kindLabel(item.kind)}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-xs text-stone-700">{actionLabel(item.action)}</td>
                      <td className={item.amount >= 0 ? "px-4 py-3 font-data text-xs font-semibold text-emerald-700" : "px-4 py-3 font-data text-xs font-semibold text-rose-700"}>
                        {item.amount >= 0 ? "+" : ""}{item.amount}
                      </td>
                      <td className="px-4 py-3 font-data text-xs text-stone-600">{remainingText(item)}</td>
                      <td className="px-4 py-3 text-xs text-stone-600">
                        <div className="max-w-[320px] truncate">{item.note || item.source || "-"}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {items.length === 0 ? (
                <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
                  <div className="rounded-xl bg-stone-100 p-3 text-stone-500">
                    <Coins className="size-5" />
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-stone-700">暂无额度流水</p>
                    <p className="text-sm text-stone-500">后续注册、兑换、扣费和返还会自动记录。</p>
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 text-center">
      <div className="font-data text-sm font-semibold text-stone-900">{value}</div>
      <div className="mt-0.5 text-[11px] text-stone-500">{label}</div>
    </div>
  );
}
