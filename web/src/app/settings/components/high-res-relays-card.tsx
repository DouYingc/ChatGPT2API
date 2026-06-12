"use client";

import { BarChart3, CheckCircle2, Clock3, Info, LoaderCircle, PlugZap, Plus, Save, Trash2, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  createHighResRelay,
  deleteHighResRelay,
  fetchHighResRelays,
  testHighResRelay,
  updateHighResRelay,
  type HighResRelay,
  type HighResRelayTestResult,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useSettingsStore, type ImageRoute, type ImageRouteKey } from "../store";

type RelayDraft = {
  name: string;
  base_url: string;
  api_key: string;
  model: string;
  mode: "images";
  enabled: boolean;
};

const IMAGE_ROUTE_CONTROLS: Array<{
  key: ImageRouteKey;
  label: string;
  defaultRoute: ImageRoute;
  poolLabel: string;
}> = [
  { key: "image_route_1k", label: "1K", defaultRoute: "pool", poolLabel: "号池" },
  { key: "image_route_2k", label: "2K", defaultRoute: "relay", poolLabel: "Plus号池" },
  { key: "image_route_4k", label: "4K", defaultRoute: "relay", poolLabel: "Plus号池" },
];

const EMPTY_DRAFT: RelayDraft = {
  name: "",
  base_url: "",
  api_key: "",
  model: "gpt-image-2",
  mode: "images",
  enabled: true,
};

const INPUT_CLASS = "h-10 rounded-xl border-stone-200 bg-white";
const LABEL_CLASS = "text-xs font-medium text-stone-500";

function draftFromRelay(relay: HighResRelay): RelayDraft {
  return {
    name: relay.name || "",
    base_url: relay.base_url || "",
    api_key: "",
    model: relay.model || "gpt-image-2",
    mode: "images",
    enabled: Boolean(relay.enabled),
  };
}

function formatDate(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatDuration(ms?: number) {
  const value = Math.max(0, Number(ms || 0));
  if (!value) return "-";
  if (value < 1000) return `${Math.round(value)} ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)} s`;
  const minutes = Math.floor(value / 60_000);
  const seconds = Math.round((value % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function formatRate(success?: number, fail?: number) {
  const ok = Math.max(0, Number(success || 0));
  const bad = Math.max(0, Number(fail || 0));
  const total = ok + bad;
  if (!total) return "-";
  return `${Math.round((ok / total) * 100)}%`;
}

export function HighResRelaysCard() {
  const config = useSettingsStore((state) => state.config);
  const setHighResRelayFailThreshold = useSettingsStore((state) => state.setHighResRelayFailThreshold);
  const setHighResRelayCooldownSeconds = useSettingsStore((state) => state.setHighResRelayCooldownSeconds);
  const setImageRoute = useSettingsStore((state) => state.setImageRoute);
  const [items, setItems] = useState<HighResRelay[]>([]);
  const [drafts, setDrafts] = useState<Record<string, RelayDraft>>({});
  const [newDraft, setNewDraft] = useState<RelayDraft>(EMPTY_DRAFT);
  const [isLoading, setIsLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, HighResRelayTestResult>>({});
  const [detailRelay, setDetailRelay] = useState<HighResRelay | null>(null);

  const enabledCount = useMemo(() => items.filter((item) => item.enabled).length, [items]);
  const pausedCount = useMemo(() => items.filter((item) => item.temporarily_paused).length, [items]);

  const loadItems = async (silent = false) => {
    if (!silent) setIsLoading(true);
    try {
      const data = await fetchHighResRelays();
      setItems(data.items);
      setDetailRelay((current) => current ? (data.items.find((item) => item.id === current.id) ?? current) : null);
      setDrafts((current) => {
        const next: Record<string, RelayDraft> = {};
        for (const item of data.items) {
          next[item.id] = current[item.id] ?? draftFromRelay(item);
        }
        return next;
      });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载中转接口失败");
    } finally {
      if (!silent) setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadItems();
  }, []);

  const updateDraft = (relayId: string, updates: Partial<RelayDraft>) => {
    setDrafts((current) => ({
      ...current,
      [relayId]: {
        ...(current[relayId] ?? EMPTY_DRAFT),
        ...updates,
      },
    }));
  };

  const handleCreate = async () => {
    if (!newDraft.base_url.trim()) {
      toast.error("请填写中转接口 Base URL");
      return;
    }
    if (!newDraft.api_key.trim()) {
      toast.error("请填写中转接口 API Key");
      return;
    }
    setSavingId("__new__");
    try {
      const data = await createHighResRelay({
        name: newDraft.name.trim(),
        base_url: newDraft.base_url.trim(),
        api_key: newDraft.api_key.trim(),
        model: newDraft.model.trim() || "gpt-image-2",
        mode: "images",
        enabled: newDraft.enabled,
      });
      setItems(data.items);
      setDrafts(Object.fromEntries(data.items.map((item) => [item.id, draftFromRelay(item)])));
      setNewDraft(EMPTY_DRAFT);
      toast.success("中转接口已添加");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "添加中转接口失败");
    } finally {
      setSavingId(null);
    }
  };

  const handleSave = async (relay: HighResRelay) => {
    const draft = drafts[relay.id] ?? draftFromRelay(relay);
    setSavingId(relay.id);
    try {
      const data = await updateHighResRelay(relay.id, {
        name: draft.name.trim(),
        base_url: draft.base_url.trim(),
        ...(draft.api_key.trim() ? { api_key: draft.api_key.trim() } : {}),
        model: draft.model.trim() || "gpt-image-2",
        mode: "images",
        enabled: draft.enabled,
      });
      setItems(data.items);
      setDrafts(Object.fromEntries(data.items.map((item) => [item.id, draftFromRelay(item)])));
      setDetailRelay((current) => current ? (data.items.find((item) => item.id === current.id) ?? current) : null);
      toast.success("中转接口已保存");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存中转接口失败");
    } finally {
      setSavingId(null);
    }
  };

  const handleDelete = async (relay: HighResRelay) => {
    if (typeof window !== "undefined" && !window.confirm(`删除「${relay.name || relay.base_url}」？`)) {
      return;
    }
    setDeletingId(relay.id);
    try {
      const data = await deleteHighResRelay(relay.id);
      setItems(data.items);
      setDrafts(Object.fromEntries(data.items.map((item) => [item.id, draftFromRelay(item)])));
      setDetailRelay((current) => current?.id === relay.id ? null : current);
      toast.success("中转接口已删除");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除中转接口失败");
    } finally {
      setDeletingId(null);
    }
  };

  const handleTest = async (relay: HighResRelay) => {
    setTestingId(relay.id);
    try {
      const data = await testHighResRelay(relay.id);
      setTestResults((current) => ({ ...current, [relay.id]: data.result }));
      if (data.result.ok) {
        toast.success(`中转接口可连接（HTTP ${data.result.status}，${data.result.latency_ms} ms）`);
      } else {
        toast.error(data.result.error || "中转接口测试失败");
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "测试中转接口失败");
    } finally {
      setTestingId(null);
      void loadItems(true);
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center rounded-xl border border-stone-200 bg-white">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-md border border-stone-200 bg-white px-2 py-1 text-xs font-medium text-stone-600">
          已配置 {items.length}
        </span>
        <span className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700">
          启用 {enabledCount}
        </span>
        {pausedCount > 0 ? (
          <span className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700">
            临时暂停 {pausedCount}
          </span>
        ) : null}
        <span className="text-xs text-stone-500">
          生图请求会按下方渠道策略选择号池或中转接口。
        </span>
      </div>

      <div className="rounded-xl border border-stone-200 bg-stone-50/60 p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-stone-900">
          <PlugZap className="size-4 text-stone-500" />
          生成渠道
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {IMAGE_ROUTE_CONTROLS.map((item) => {
            const currentRoute = String(config?.[item.key] || item.defaultRoute) === "relay" ? "relay" : "pool";
            return (
              <div key={item.key} className="rounded-lg border border-stone-200 bg-white p-3">
                <div className="mb-2 text-xs font-semibold text-stone-600">{item.label}</div>
                <div className="grid grid-cols-2 gap-2">
                  {([
                    ["pool", item.poolLabel],
                    ["relay", "中转"],
                  ] as const).map(([route, label]) => (
                    <Button
                      key={route}
                      type="button"
                      variant="outline"
                      className={cn(
                        "h-9 rounded-lg border-stone-200 text-xs",
                        currentRoute === route
                          ? "border-stone-900 bg-stone-900 text-white hover:bg-stone-800 hover:text-white"
                          : "bg-white text-stone-600 hover:bg-stone-50",
                      )}
                      onClick={() => setImageRoute(item.key, route)}
                    >
                      {label}
                    </Button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
        <p className="mt-2 text-xs text-stone-500">
          2K/4K 选择 Plus号池时只会使用 Plus、Pro、Team 账号；选择中转时使用下方启用接口。
        </p>
      </div>

      <div className="rounded-xl border border-stone-200 bg-stone-50/60 p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-stone-900">
          <PlugZap className="size-4 text-stone-500" />
          自动熔断
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1.5">
            <span className={LABEL_CLASS}>连续失败阈值</span>
            <Input
              value={String(config?.high_res_relay_fail_threshold ?? 3)}
              onChange={(event) => setHighResRelayFailThreshold(event.target.value)}
              placeholder="3"
              className={INPUT_CLASS}
            />
          </label>
          <label className="space-y-1.5">
            <span className={LABEL_CLASS}>暂停冷却时间（秒）</span>
            <Input
              value={String(config?.high_res_relay_cooldown_seconds ?? 300)}
              onChange={(event) => setHighResRelayCooldownSeconds(event.target.value)}
              placeholder="300"
              className={INPUT_CLASS}
            />
          </label>
        </div>
        <p className="mt-2 text-xs text-stone-500">
          达到阈值后系统会临时跳过该接口，冷却结束后自动恢复尝试。
        </p>
      </div>

      <div className="rounded-xl border border-stone-200 bg-stone-50/60 p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-stone-900">
          <Plus className="size-4 text-stone-500" />
          添加中转接口
        </div>
        <div className="grid gap-3 md:grid-cols-[1fr_1.4fr_0.9fr_1fr_0.8fr]">
          <label className="space-y-1.5">
            <span className={LABEL_CLASS}>名称</span>
            <Input
              value={newDraft.name}
              onChange={(event) => setNewDraft((current) => ({ ...current, name: event.target.value }))}
              placeholder="例如：Duck"
              className={INPUT_CLASS}
            />
          </label>
          <label className="space-y-1.5">
            <span className={LABEL_CLASS}>Base URL</span>
            <Input
              value={newDraft.base_url}
              onChange={(event) => setNewDraft((current) => ({ ...current, base_url: event.target.value }))}
              placeholder="https://www.duckcoding.ai"
              className={INPUT_CLASS}
            />
            <span className="text-[11px] text-stone-400">可填根域名或 /v1，系统会自动请求 /v1/images/generations。</span>
          </label>
          <label className="space-y-1.5">
            <span className={LABEL_CLASS}>调用方式</span>
            <div className={cn(INPUT_CLASS, "flex items-center px-3 text-sm text-stone-700")}>Images API</div>
          </label>
          <label className="space-y-1.5">
            <span className={LABEL_CLASS}>API Key</span>
            <Input
              value={newDraft.api_key}
              onChange={(event) => setNewDraft((current) => ({ ...current, api_key: event.target.value }))}
              placeholder="sk-..."
              type="password"
              className={INPUT_CLASS}
            />
          </label>
          <label className="space-y-1.5">
            <span className={LABEL_CLASS}>模型</span>
            <Input
              value={newDraft.model}
              onChange={(event) => setNewDraft((current) => ({ ...current, model: event.target.value }))}
              placeholder="gpt-image-2"
              className={INPUT_CLASS}
            />
          </label>
        </div>
        <div className="mt-3 flex items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-sm text-stone-700">
            <Checkbox
              checked={newDraft.enabled}
              onCheckedChange={(checked) => setNewDraft((current) => ({ ...current, enabled: Boolean(checked) }))}
            />
            立即启用
          </label>
          <Button
            type="button"
            className="h-9 rounded-xl bg-stone-900 text-white hover:bg-stone-800"
            onClick={() => void handleCreate()}
            disabled={savingId === "__new__"}
          >
            {savingId === "__new__" ? <LoaderCircle className="size-4 animate-spin" /> : <Plus className="size-4" />}
            添加
          </Button>
        </div>
      </div>

      <div className="space-y-3">
        {items.length === 0 ? (
          <div className="rounded-xl border border-dashed border-stone-300 bg-white px-4 py-8 text-center text-sm text-stone-500">
            暂无中转接口
          </div>
        ) : (
          items.map((relay) => {
            const draft = drafts[relay.id] ?? draftFromRelay(relay);
            const testResult = testResults[relay.id];
            return (
              <div key={relay.id} className="rounded-xl border border-stone-200 bg-white p-4">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-semibold text-stone-900">{relay.name || relay.base_url}</span>
                      <span
                        className={cn(
                          "rounded-md px-2 py-0.5 text-[11px] font-medium",
                          relay.temporarily_paused
                            ? "bg-amber-50 text-amber-700"
                            : relay.enabled ? "bg-emerald-50 text-emerald-700" : "bg-stone-100 text-stone-500",
                        )}
                      >
                        {relay.temporarily_paused ? "临时暂停" : relay.enabled ? "启用" : "停用"}
                      </span>
                      <span className="rounded-md bg-stone-100 px-2 py-0.5 text-[11px] font-medium text-stone-500">
                        {relay.has_api_key ? "已配置密钥" : "缺少密钥"}
                      </span>
                      <span className="rounded-md bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-700">
                        Images API
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-stone-400">
                      成功 {relay.success} · 失败 {relay.fail}
                      {relay.last_used_at ? ` · 最近 ${formatDate(relay.last_used_at)}` : ""}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-stone-500">
                      <span className="inline-flex items-center gap-1 rounded-md bg-stone-100 px-2 py-1">
                        <BarChart3 className="size-3" />
                        今日成功率 {formatRate(relay.today_success, relay.today_fail)}
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-md bg-stone-100 px-2 py-1">
                        <BarChart3 className="size-3" />
                        总成功率 {formatRate(relay.success, relay.fail)}
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-md bg-stone-100 px-2 py-1">
                        <Clock3 className="size-3" />
                        今日均时 {formatDuration(relay.today_avg_duration_ms)}
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-md bg-stone-100 px-2 py-1">
                        <Clock3 className="size-3" />
                        总均时 {formatDuration(relay.avg_duration_ms)}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      className="h-9 rounded-xl border-stone-200 bg-white"
                      onClick={() => setDetailRelay(relay)}
                    >
                      <Info className="size-4" />
                      详情
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-9 rounded-xl border-stone-200 bg-white"
                      onClick={() => void handleTest(relay)}
                      disabled={testingId === relay.id}
                    >
                      {testingId === relay.id ? <LoaderCircle className="size-4 animate-spin" /> : <PlugZap className="size-4" />}
                      测试
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-9 rounded-xl border-stone-200 bg-white"
                      onClick={() => void handleSave(relay)}
                      disabled={savingId === relay.id}
                    >
                      {savingId === relay.id ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
                      保存
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-9 rounded-xl border-stone-200 bg-white text-rose-600 hover:text-rose-700"
                      onClick={() => void handleDelete(relay)}
                      disabled={deletingId === relay.id}
                    >
                      {deletingId === relay.id ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                    </Button>
                  </div>
                </div>

                <div className="grid gap-3 md:grid-cols-[1fr_1.4fr_0.9fr_1fr_0.8fr]">
                  <label className="space-y-1.5">
                    <span className={LABEL_CLASS}>名称</span>
                    <Input
                      value={draft.name}
                      onChange={(event) => updateDraft(relay.id, { name: event.target.value })}
                      className={INPUT_CLASS}
                    />
                  </label>
                  <label className="space-y-1.5">
                    <span className={LABEL_CLASS}>Base URL</span>
                    <Input
                      value={draft.base_url}
                      onChange={(event) => updateDraft(relay.id, { base_url: event.target.value })}
                      className={INPUT_CLASS}
                    />
                    <span className="text-[11px] text-stone-400">可填根域名或 /v1。</span>
                  </label>
                  <label className="space-y-1.5">
                    <span className={LABEL_CLASS}>调用方式</span>
                    <div className={cn(INPUT_CLASS, "flex items-center px-3 text-sm text-stone-700")}>Images API</div>
                  </label>
                  <label className="space-y-1.5">
                    <span className={LABEL_CLASS}>API Key</span>
                    <Input
                      value={draft.api_key}
                      onChange={(event) => updateDraft(relay.id, { api_key: event.target.value })}
                      placeholder="留空则不修改"
                      type="password"
                      className={INPUT_CLASS}
                    />
                  </label>
                  <label className="space-y-1.5">
                    <span className={LABEL_CLASS}>模型</span>
                    <Input
                      value={draft.model}
                      onChange={(event) => updateDraft(relay.id, { model: event.target.value })}
                      className={INPUT_CLASS}
                    />
                  </label>
                </div>

                <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                  <label className="flex items-center gap-2 text-sm text-stone-700">
                    <Checkbox
                      checked={draft.enabled}
                      onCheckedChange={(checked) => updateDraft(relay.id, { enabled: Boolean(checked) })}
                    />
                    启用这个接口
                  </label>
                  {testResult ? (
                    <div
                      className={cn(
                        "flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs",
                        testResult.ok ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700",
                      )}
                    >
                      {testResult.ok ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}
                      {testResult.ok
                        ? `HTTP ${testResult.status} · ${testResult.latency_ms} ms`
                        : testResult.error || "测试失败"}
                    </div>
                  ) : relay.temporarily_paused ? (
                    <div className="max-w-full truncate rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs text-amber-700">
                      已临时暂停：{relay.pause_reason || "连续失败"}，预计 {formatDate(relay.paused_until)} 恢复
                    </div>
                  ) : relay.last_error ? (
                    <div className="max-w-full truncate rounded-lg bg-rose-50 px-2.5 py-1.5 text-xs text-rose-700">
                      最近错误：{relay.last_error}
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })
        )}
      </div>

      <Dialog open={Boolean(detailRelay)} onOpenChange={(open) => !open && setDetailRelay(null)}>
        <DialogContent className="max-w-xl rounded-2xl">
          <DialogHeader>
            <DialogTitle>{detailRelay?.name || detailRelay?.base_url || "中转接口详情"}</DialogTitle>
            <DialogDescription>查看接口调用统计、最近状态和基础配置。</DialogDescription>
          </DialogHeader>
          {detailRelay ? (
            <div className="space-y-4">
              <div className="grid gap-2 sm:grid-cols-2">
                <DetailStat label="今日成功率" value={formatRate(detailRelay.today_success, detailRelay.today_fail)} />
                <DetailStat label="总成功率" value={formatRate(detailRelay.success, detailRelay.fail)} />
                <DetailStat label="今日成功/失败" value={`${detailRelay.today_success ?? 0} / ${detailRelay.today_fail ?? 0}`} />
                <DetailStat label="总成功/失败" value={`${detailRelay.success} / ${detailRelay.fail}`} />
                <DetailStat label="今日平均耗时" value={formatDuration(detailRelay.today_avg_duration_ms)} />
                <DetailStat label="总平均耗时" value={formatDuration(detailRelay.avg_duration_ms)} />
                <DetailStat label="连续失败" value={`${detailRelay.consecutive_fail ?? 0}`} />
                <DetailStat label="暂停状态" value={detailRelay.temporarily_paused ? "临时暂停" : "正常"} />
              </div>
              <div className="rounded-xl border border-stone-200 bg-stone-50/60 p-3 text-sm">
                <div className="grid gap-2 text-stone-600 sm:grid-cols-[90px_1fr]">
                  <span className="text-stone-400">Base URL</span>
                  <span className="break-all font-data text-xs text-stone-800">{detailRelay.base_url}</span>
                  <span className="text-stone-400">模型</span>
                  <span className="font-data text-xs text-stone-800">{detailRelay.model}</span>
                  <span className="text-stone-400">状态</span>
                  <span>{detailRelay.enabled ? "启用" : "停用"} · {detailRelay.has_api_key ? "已配置密钥" : "缺少密钥"}</span>
                  <span className="text-stone-400">最近使用</span>
                  <span>{detailRelay.last_used_at ? formatDate(detailRelay.last_used_at) : "-"}</span>
                  <span className="text-stone-400">暂停到</span>
                  <span>{detailRelay.temporarily_paused && detailRelay.paused_until ? formatDate(detailRelay.paused_until) : "-"}</span>
                </div>
              </div>
              {detailRelay.temporarily_paused ? (
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
                  <div className="mb-1 font-medium">暂停原因</div>
                  <div className="break-all">{detailRelay.pause_reason || "连续失败"}</div>
                </div>
              ) : null}
              {detailRelay.last_error ? (
                <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-700">
                  <div className="mb-1 font-medium">最近错误</div>
                  <div className="break-all">{detailRelay.last_error}</div>
                </div>
              ) : null}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function DetailStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white px-3 py-2.5">
      <div className="text-[11px] text-stone-500">{label}</div>
      <div className="mt-1 font-data text-sm font-semibold text-stone-900">{value}</div>
    </div>
  );
}
