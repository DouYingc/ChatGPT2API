"use client";

import { useEffect, useMemo, useState } from "react";
import { Copy, Download, LoaderCircle, Plus, Search, Ticket, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  createRedeemCodes,
  deleteRedeemCode,
  fetchRedeemCodes,
  type RedeemCode,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const AMOUNTS = [100, 500, 1000];

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

async function copyToClipboard(value: string) {
  try {
    await navigator.clipboard.writeText(value);
    toast.success("已复制兑换码");
  } catch {
    toast.error("复制失败，请手动复制");
  }
}

function buildCodeText(codes: RedeemCode[]) {
  return codes.map((item) => item.code).filter(Boolean).join("\n");
}

function downloadText(filename: string, content: string) {
  if (typeof document === "undefined") return;
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function exportCodes(codes: RedeemCode[], filename: string) {
  const content = buildCodeText(codes);
  if (!content) {
    toast.error("没有可导出的兑换码");
    return;
  }
  downloadText(filename, `${content}\n`);
  toast.success(`已导出 ${codes.length} 个兑换码`);
}

async function copyCodes(codes: RedeemCode[]) {
  const content = buildCodeText(codes);
  if (!content) {
    toast.error("没有可复制的兑换码");
    return;
  }
  try {
    await navigator.clipboard.writeText(content);
    toast.success(`已复制 ${codes.length} 个兑换码`);
  } catch {
    toast.error("复制失败，请使用导出");
  }
}

export function RedeemCodesCard() {
  const [items, setItems] = useState<RedeemCode[]>([]);
  const [createdCodes, setCreatedCodes] = useState<RedeemCode[]>([]);
  const [amount, setAmount] = useState(100);
  const [quantity, setQuantity] = useState("1");
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [deletingId, setDeletingId] = useState("");

  const load = async () => {
    setIsLoading(true);
    try {
      const data = await fetchRedeemCodes();
      setItems(data.items);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载兑换码失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const filteredItems = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return items;
    return items.filter((item) => {
      const fields = [
        item.code,
        String(item.amount),
        item.used_by_name || "",
        item.created_by_name || "",
      ];
      return fields.some((field) => String(field).toLowerCase().includes(normalized));
    });
  }, [items, query]);

  const stats = useMemo(() => {
    const unused = items.filter((item) => !item.used).length;
    const used = items.length - unused;
    return { total: items.length, unused, used };
  }, [items]);
  const exportableAmountCodes = useMemo(
    () => items.filter((item) => !item.used && Number(item.amount) === amount),
    [amount, items],
  );

  const handleCreate = async () => {
    const count = Math.max(1, Math.min(100, Math.floor(Number(quantity) || 1)));
    setIsCreating(true);
    try {
      const data = await createRedeemCodes({ amount, quantity: count });
      setItems(data.items);
      setCreatedCodes(data.created);
      setQuantity("1");
      toast.success(`已生成 ${data.created.length} 个 ${amount} 额度兑换码`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "生成兑换码失败");
    } finally {
      setIsCreating(false);
    }
  };

  const handleDelete = async (item: RedeemCode) => {
    setDeletingId(item.id);
    try {
      const data = await deleteRedeemCode(item.id);
      setItems(data.items);
      setCreatedCodes((current) => current.filter((code) => code.id !== item.id));
      toast.success("兑换码已删除");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除兑换码失败");
    } finally {
      setDeletingId("");
    }
  };

  return (
    <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-5 p-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-stone-100">
              <Ticket className="size-5 text-stone-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-tight">兑换码管理</h2>
              <p className="text-sm text-stone-500">
                生成一次性兑换码，用户兑换后会追加画图总额度。
              </p>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2 rounded-xl border border-stone-200 bg-stone-50 p-1 text-center text-xs">
            <Stat label="总数" value={stats.total} />
            <Stat label="未用" value={stats.unused} />
            <Stat label="已用" value={stats.used} />
          </div>
        </div>

        <div className="grid gap-3 rounded-xl border border-stone-200 bg-stone-50/60 p-3 lg:grid-cols-[minmax(0,1fr)_110px_120px] lg:items-end">
          <div className="space-y-2">
            <label className="text-xs font-semibold tracking-wide text-stone-500 uppercase">额度面额</label>
            <div className="grid grid-cols-3 gap-2">
              {AMOUNTS.map((value) => {
                const selected = amount === value;
                return (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setAmount(value)}
                    className={cn(
                      "h-10 cursor-pointer rounded-xl border text-sm font-semibold transition",
                      selected
                        ? "border-stone-900 bg-stone-900 text-white"
                        : "border-stone-200 bg-white text-stone-600 hover:bg-stone-100",
                    )}
                  >
                    {value}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-xs font-semibold tracking-wide text-stone-500 uppercase">数量</label>
            <Input
              type="number"
              min={1}
              max={100}
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              className="h-10 rounded-xl border-stone-200 bg-white font-data shadow-none"
            />
          </div>
          <Button
            type="button"
            className="h-10 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800"
            onClick={() => void handleCreate()}
            disabled={isCreating}
          >
            {isCreating ? <LoaderCircle className="size-4 animate-spin" /> : <Plus className="size-4" />}
            生成
          </Button>
        </div>

        {createdCodes.length > 0 ? (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-4 text-sm text-emerald-900">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-medium">刚生成的兑换码</div>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="h-8 rounded-lg border-emerald-200 bg-white/80 px-2.5 text-xs text-emerald-800 hover:bg-white"
                  onClick={() => void copyCodes(createdCodes)}
                >
                  <Copy className="size-3.5" />
                  复制本次
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="h-8 rounded-lg border-emerald-200 bg-white/80 px-2.5 text-xs text-emerald-800 hover:bg-white"
                  onClick={() => exportCodes(createdCodes, `redeem-codes-${createdCodes[0]?.amount || amount}-${Date.now()}.txt`)}
                >
                  <Download className="size-3.5" />
                  导出本次
                </Button>
              </div>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {createdCodes.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => void copyToClipboard(item.code)}
                  className="flex cursor-pointer items-center justify-between gap-2 rounded-lg border border-emerald-200 bg-white/80 px-3 py-2 text-left font-data text-[12px] text-emerald-950 transition hover:bg-white"
                >
                  <span className="truncate">{item.code}</span>
                  <Copy className="size-3.5 shrink-0" />
                </button>
              ))}
            </div>
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="relative min-w-[220px]">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-stone-400" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索兑换码或使用人"
              className="h-9 rounded-xl border-stone-200 bg-white/85 pl-10"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              className="h-9 rounded-xl border-stone-200 bg-white"
              onClick={() => void copyCodes(exportableAmountCodes)}
              disabled={exportableAmountCodes.length === 0}
            >
              <Copy className="size-4" />
              复制未用 {amount}
            </Button>
            <Button
              type="button"
              variant="outline"
              className="h-9 rounded-xl border-stone-200 bg-white"
              onClick={() => exportCodes(exportableAmountCodes, `redeem-codes-${amount}-unused-${Date.now()}.txt`)}
              disabled={exportableAmountCodes.length === 0}
            >
              <Download className="size-4" />
              导出未用 {amount}
            </Button>
            <Button
              type="button"
              variant="outline"
              className="h-9 rounded-xl border-stone-200 bg-white"
              onClick={() => void load()}
              disabled={isLoading}
            >
              {isLoading ? <LoaderCircle className="size-4 animate-spin" /> : null}
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
              <table className="w-full min-w-[860px] text-left text-sm">
                <thead className="border-b border-stone-200 bg-stone-50 text-[12px] font-medium text-stone-500">
                  <tr>
                    <th className="w-56 px-4 py-2.5 font-medium">兑换码</th>
                    <th className="w-24 px-4 py-2.5 font-medium">额度</th>
                    <th className="w-24 px-4 py-2.5 font-medium">状态</th>
                    <th className="w-44 px-4 py-2.5 font-medium">使用人</th>
                    <th className="w-36 px-4 py-2.5 font-medium">创建时间</th>
                    <th className="w-36 px-4 py-2.5 font-medium">使用时间</th>
                    <th className="w-24 px-4 py-2.5 text-right font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.map((item) => (
                    <tr key={item.id} className="border-b border-stone-100 even:bg-stone-50/40 hover:bg-stone-50">
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => void copyToClipboard(item.code)}
                          className="inline-flex cursor-pointer items-center gap-2 rounded-md px-1 py-0.5 font-data text-[12px] text-stone-800 transition hover:bg-stone-100"
                        >
                          {item.code}
                          <Copy className="size-3.5 text-stone-400" />
                        </button>
                      </td>
                      <td className="px-4 py-3 font-data text-xs text-stone-700">+{item.amount}</td>
                      <td className="px-4 py-3">
                        <Badge variant={item.used ? "secondary" : "success"} className="rounded-md">
                          {item.used ? "已使用" : "未使用"}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-xs text-stone-600">
                        {item.used_by_name || item.used_by || "-"}
                      </td>
                      <td className="px-4 py-3 font-data text-xs text-stone-500">
                        {formatDateTime(item.created_at)}
                      </td>
                      <td className="px-4 py-3 font-data text-xs text-stone-500">
                        {formatDateTime(item.used_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end">
                          <button
                            type="button"
                            className="cursor-pointer rounded-md p-1.5 text-stone-500 transition hover:bg-rose-50 hover:text-rose-600 disabled:opacity-50"
                            onClick={() => void handleDelete(item)}
                            disabled={deletingId === item.id}
                            title="删除"
                          >
                            {deletingId === item.id ? (
                              <LoaderCircle className="size-4 animate-spin" />
                            ) : (
                              <Trash2 className="size-4" />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {filteredItems.length === 0 ? (
                <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
                  <div className="rounded-xl bg-stone-100 p-3 text-stone-500">
                    <Ticket className="size-5" />
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-stone-700">
                      {query.trim() ? "没有匹配的兑换码" : "暂无兑换码"}
                    </p>
                    <p className="text-sm text-stone-500">
                      {query.trim() ? "调整搜索关键字后重试。" : "选择额度和数量后即可生成。"}
                    </p>
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
    <div className="min-w-16 rounded-lg bg-white px-3 py-2">
      <div className="font-data text-base font-semibold text-stone-900">{value}</div>
      <div className="mt-0.5 text-[11px] text-stone-500">{label}</div>
    </div>
  );
}
