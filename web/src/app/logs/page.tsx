"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ChevronLeft, ChevronRight, ImageIcon, LoaderCircle, RefreshCw, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { DateRangeFilter } from "@/components/date-range-filter";
import { ImageLightbox } from "@/components/image-lightbox";
import { ImageThumbnail, getImageThumbnailUrl } from "@/components/image-thumbnail";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { deleteSystemLogs, fetchSystemLogs, type SystemLog } from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";

const LogType = {
  Call: "call",
  Account: "account",
} as const;

const typeLabels: Record<string, string> = {
  [LogType.Call]: "调用日志",
  [LogType.Account]: "账号管理日志",
};

type CallStatusFilter = "all" | "success" | "failed";
type CallKindFilter = "all" | "image" | "text";
type ResolutionFilter = "all" | "1k" | "2k" | "4k" | "unknown";
type ImageRouteFilter = "all" | "pool" | "relay" | "unknown";
type ErrorKindFilter = "all" | "relay" | "account_limit" | "network" | "content_policy" | "other";

const callStatusOptions: { label: string; value: CallStatusFilter }[] = [
  { label: "全部状态", value: "all" },
  { label: "成功", value: "success" },
  { label: "失败", value: "failed" },
];

const callKindOptions: { label: string; value: CallKindFilter }[] = [
  { label: "全部调用", value: "all" },
  { label: "只看生图", value: "image" },
  { label: "只看文本", value: "text" },
];

const resolutionOptions: { label: string; value: ResolutionFilter }[] = [
  { label: "全部清晰度", value: "all" },
  { label: "1K", value: "1k" },
  { label: "2K", value: "2k" },
  { label: "4K", value: "4k" },
  { label: "未知", value: "unknown" },
];

const imageRouteOptions: { label: string; value: ImageRouteFilter }[] = [
  { label: "全部渠道", value: "all" },
  { label: "号池", value: "pool" },
  { label: "中转", value: "relay" },
  { label: "未知渠道", value: "unknown" },
];

const errorKindOptions: { label: string; value: ErrorKindFilter }[] = [
  { label: "全部错误", value: "all" },
  { label: "中转失败", value: "relay" },
  { label: "账号/额度", value: "account_limit" },
  { label: "网络断连", value: "network" },
  { label: "内容策略", value: "content_policy" },
  { label: "其他错误", value: "other" },
];

function getDetailText(item: SystemLog, key: string) {
  const value = item.detail?.[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : "-";
}

function formatDuration(item: SystemLog) {
  const value = item.detail?.duration_ms;
  return typeof value === "number" ? `${(value / 1000).toFixed(2)} s` : "-";
}

function getUrls(item: SystemLog | null) {
  const urls = item?.detail?.urls;
  return Array.isArray(urls) ? urls.filter((url): url is string => typeof url === "string") : [];
}

function getStatus(item: SystemLog) {
  const status = item.detail?.status;
  if (status === "success") return "成功";
  if (status === "failed") return "失败";
  return "-";
}

function getStatusFilterValue(item: SystemLog): CallStatusFilter | "unknown" {
  const status = item.detail?.status;
  if (status === "success" || status === "failed") return status;
  return "unknown";
}

function isImageCallLog(item: SystemLog) {
  const endpoint = String(item.detail?.endpoint || "").toLowerCase();
  const summary = String(item.summary || "");
  return endpoint.includes("/images/") || endpoint.includes("/image-tasks/") || summary.includes("生图");
}

function normalizeResolution(value: unknown): ResolutionFilter {
  const text = String(value || "").trim().toLowerCase().replace(/\s+/g, "");
  if (text === "1k" || text === "2k" || text === "4k") return text;
  if (text.includes("4096") || text.includes("4k")) return "4k";
  if (text.includes("2048") || text.includes("2k")) return "2k";
  if (text.includes("1024") || text.includes("1k")) return "1k";
  return "unknown";
}

function getResolution(item: SystemLog): ResolutionFilter {
  const resolution = normalizeResolution(item.detail?.resolution);
  if (resolution !== "unknown") return resolution;
  return normalizeResolution(item.detail?.size);
}

function getImageRoute(item: SystemLog): ImageRouteFilter {
  const route = String(item.detail?.image_route || item.detail?.route || "").trim().toLowerCase();
  if (route === "pool" || route === "relay") return route;
  const error = String(item.detail?.error || "").toLowerCase();
  if (error.includes("中转") || error.includes("duck") || error.includes("relay")) return "relay";
  return "unknown";
}

function getErrorKind(item: SystemLog): ErrorKindFilter | "none" {
  if (item.detail?.status !== "failed") return "none";
  const error = String(item.detail?.error || item.summary || "").toLowerCase();
  if (error.includes("中转") || error.includes("duck") || error.includes("relay")) return "relay";
  if (
    error.includes("quota")
    || error.includes("free plan limit")
    || error.includes("no available image")
    || error.includes("usage_limit")
    || error.includes("rate_limit")
    || error.includes("限流")
    || error.includes("额度")
  ) {
    return "account_limit";
  }
  if (
    error.includes("socket")
    || error.includes("econnreset")
    || error.includes("und_err")
    || error.includes("timeout")
    || error.includes("connection")
    || error.includes("fetch failed")
  ) {
    return "network";
  }
  if (
    error.includes("content_policy")
    || error.includes("policy")
    || error.includes("blocked")
    || error.includes("rejected")
    || error.includes("敏感")
  ) {
    return "content_policy";
  }
  return "other";
}

function errorKindLabel(kind: ReturnType<typeof getErrorKind>) {
  if (kind === "relay") return "中转失败";
  if (kind === "account_limit") return "账号/额度";
  if (kind === "network") return "网络断连";
  if (kind === "content_policy") return "内容策略";
  if (kind === "other") return "其他错误";
  return "";
}

function routeLabel(route: ImageRouteFilter) {
  if (route === "pool") return "号池";
  if (route === "relay") return "中转";
  return "未知渠道";
}

function resolutionLabel(resolution: ResolutionFilter) {
  return resolution === "unknown" ? "未知清晰度" : resolution.toUpperCase();
}

function todayKey() {
  const date = new Date();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function normalizeDateParam(value: string | null) {
  if (!value) return "";
  return value === "today" ? todayKey() : value;
}

function parseLogFilters(params: URLSearchParams) {
  const status = params.get("status");
  const kind = params.get("kind");
  const resolution = params.get("resolution");
  const route = params.get("route");
  const error = params.get("error");
  const date = normalizeDateParam(params.get("date"));
  const startDate = normalizeDateParam(params.get("start_date")) || date;
  const endDate = normalizeDateParam(params.get("end_date")) || date;
  return {
    type: params.get("type") || LogType.Call,
    startDate,
    endDate,
    callStatusFilter: status === "success" || status === "failed" ? status : "all",
    callKindFilter: kind === "image" || kind === "text" ? kind : "all",
    resolutionFilter:
      resolution === "1k" || resolution === "2k" || resolution === "4k" || resolution === "unknown"
        ? resolution
        : "all",
    imageRouteFilter:
      route === "pool" || route === "relay" || route === "unknown" ? route : "all",
    errorKindFilter:
      error === "relay" || error === "account_limit" || error === "network" || error === "content_policy" || error === "other"
        ? error
        : "all",
  } satisfies {
    type: string;
    startDate: string;
    endDate: string;
    callStatusFilter: CallStatusFilter;
    callKindFilter: CallKindFilter;
    resolutionFilter: ResolutionFilter;
    imageRouteFilter: ImageRouteFilter;
    errorKindFilter: ErrorKindFilter;
  };
}

// 模块级缓存：路由切换会让 LogsContent 重新挂载，
// 不缓存的话每次切回都会从 items=[] / isLoading=true 起跳，
// 表格高度从 0 撑到 N 行，体感"跳一下"。
type LogsCache = {
  items: SystemLog[];
  type: string;
  startDate: string;
  endDate: string;
};
let cachedLogs: LogsCache | null = null;

function LogsContent() {
  const searchParams = useSearchParams();
  const initialFilters = useMemo(() => parseLogFilters(searchParams), [searchParams]);
  // 命中缓存时直接拿来当初始 state；filter 也按上次结果回填，
  // 避免切回 logs 页 type/startDate/endDate 重置后立即触发一次空查询。
  const [items, setItemsState] = useState<SystemLog[]>(() => cachedLogs?.items ?? []);
  const [type, setType] = useState<string>(() => initialFilters.type || cachedLogs?.type || LogType.Call);
  const [startDate, setStartDate] = useState(() => initialFilters.startDate || cachedLogs?.startDate || "");
  const [endDate, setEndDate] = useState(() => initialFilters.endDate || cachedLogs?.endDate || "");
  const [callStatusFilter, setCallStatusFilter] = useState<CallStatusFilter>(initialFilters.callStatusFilter);
  const [callKindFilter, setCallKindFilter] = useState<CallKindFilter>(initialFilters.callKindFilter);
  const [resolutionFilter, setResolutionFilter] = useState<ResolutionFilter>(initialFilters.resolutionFilter);
  const [imageRouteFilter, setImageRouteFilter] = useState<ImageRouteFilter>(initialFilters.imageRouteFilter);
  const [errorKindFilter, setErrorKindFilter] = useState<ErrorKindFilter>(initialFilters.errorKindFilter);
  const [detailLog, setDetailLog] = useState<SystemLog | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(() => cachedLogs === null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [deletingItems, setDeletingItems] = useState<SystemLog[]>([]);
  const detailUrls = getUrls(detailLog);
  const detailImages = detailUrls.map((url, index) => ({ id: `${index}`, src: url }));
  const isCallLog = type === LogType.Call;
  const pageSize = 10;
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const filteredItems = useMemo(() => {
    if (!isCallLog) return items;
    return items.filter((item) => {
      if (callStatusFilter !== "all" && getStatusFilterValue(item) !== callStatusFilter) return false;
      if (callKindFilter === "image" && !isImageCallLog(item)) return false;
      if (callKindFilter === "text" && isImageCallLog(item)) return false;
      if (resolutionFilter !== "all") {
        if (!isImageCallLog(item) || getResolution(item) !== resolutionFilter) return false;
      }
      if (imageRouteFilter !== "all") {
        if (!isImageCallLog(item) || getImageRoute(item) !== imageRouteFilter) return false;
      }
      if (errorKindFilter !== "all" && getErrorKind(item) !== errorKindFilter) return false;
      return true;
    });
  }, [callKindFilter, callStatusFilter, errorKindFilter, imageRouteFilter, isCallLog, items, resolutionFilter]);
  const pageCount = Math.max(1, Math.ceil(filteredItems.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const currentRows = filteredItems.slice((safePage - 1) * pageSize, safePage * pageSize);
  const currentPageSelected = currentRows.length > 0 && currentRows.every((item) => selectedSet.has(item.id));
  const allSelected = filteredItems.length > 0 && filteredItems.every((item) => selectedSet.has(item.id));

  // 写入 items 同步刷新缓存，下次切回 logs 页能拿到最新值。
  const setItems = (next: SystemLog[]) => {
    cachedLogs = { items: next, type, startDate, endDate };
    setItemsState(next);
  };

  const loadLogs = async (silent = false) => {
    if (!silent) setIsLoading(true);
    try {
      const data = await fetchSystemLogs({ type, start_date: startDate, end_date: endDate });
      setItems(data.items);
      setSelectedIds((current) => current.filter((id) => data.items.some((item) => item.id === id)));
      setPage(1);
    } catch (error) {
      if (!silent) toast.error(error instanceof Error ? error.message : "加载日志失败");
    } finally {
      if (!silent) setIsLoading(false);
    }
  };

  const clearFilters = () => {
    setStartDate("");
    setEndDate("");
    setCallStatusFilter("all");
    setCallKindFilter("all");
    setResolutionFilter("all");
    setImageRouteFilter("all");
    setErrorKindFilter("all");
  };

  const openDetail = (item: SystemLog) => {
    setDetailLog(item);
    setDetailOpen(true);
  };

  const openLogImage = (item: SystemLog, index: number) => {
    setDetailLog(item);
    setLightboxIndex(index);
    setLightboxOpen(true);
  };

  const toggleIds = (ids: string[], checked: boolean) => {
    setSelectedIds((current) => checked ? Array.from(new Set([...current, ...ids])) : current.filter((id) => !ids.includes(id)));
  };

  const confirmDelete = async () => {
    const ids = deletingItems.map((item) => item.id);
    if (ids.length === 0) return;
    setIsDeleting(true);
    try {
      const data = await deleteSystemLogs(ids);
      toast.success(`已删除 ${data.removed} 条日志`);
      setDeletingItems([]);
      setSelectedIds((current) => current.filter((id) => !ids.includes(id)));
      if (detailLog && ids.includes(detailLog.id)) {
        setDetailOpen(false);
        setDetailLog(null);
      }
      await loadLogs();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除日志失败");
    } finally {
      setIsDeleting(false);
    }
  };

  // 首次挂载且缓存命中（filter 与缓存一致）→ 静默刷新，
  // 不让表格塌缩成空再撑回；之后用户改 filter / 删除后调用都正常 spinner。
  const isFirstRunRef = useRef(true);
  useEffect(() => {
    const isFirst = isFirstRunRef.current;
    isFirstRunRef.current = false;
    const cacheMatches =
      !!cachedLogs &&
      cachedLogs.type === type &&
      cachedLogs.startDate === startDate &&
      cachedLogs.endDate === endDate;
    void loadLogs(isFirst && cacheMatches);
  }, [type, startDate, endDate]);

  useEffect(() => {
    const query = searchParams.toString();
    if (!query) return;
    const next = parseLogFilters(searchParams);
    setType(next.type);
    setStartDate(next.startDate);
    setEndDate(next.endDate);
    setCallStatusFilter(next.callStatusFilter);
    setCallKindFilter(next.callKindFilter);
    setResolutionFilter(next.resolutionFilter);
    setImageRouteFilter(next.imageRouteFilter);
    setErrorKindFilter(next.errorKindFilter);
    setPage(1);
  }, [searchParams]);

  useEffect(() => {
    setPage(1);
    setSelectedIds([]);
  }, [callKindFilter, callStatusFilter, errorKindFilter, imageRouteFilter, resolutionFilter, type]);

  return (
    <section className="mt-4 space-y-5 sm:mt-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">Logs</div>
          <h1 className="text-2xl font-semibold tracking-tight">日志管理</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <Select value={type} onValueChange={setType}>
            <SelectTrigger className="h-10 w-[150px] rounded-xl border-stone-200 bg-white"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={LogType.Call}>调用日志</SelectItem>
              <SelectItem value={LogType.Account}>账号管理日志</SelectItem>
            </SelectContent>
          </Select>
          <DateRangeFilter startDate={startDate} endDate={endDate} onChange={(start, end) => { setStartDate(start); setEndDate(end); }} />
          {isCallLog ? (
            <>
              <Select value={callStatusFilter} onValueChange={(value) => setCallStatusFilter(value as CallStatusFilter)}>
                <SelectTrigger className="h-10 w-[120px] rounded-xl border-stone-200 bg-white"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {callStatusOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={callKindFilter} onValueChange={(value) => setCallKindFilter(value as CallKindFilter)}>
                <SelectTrigger className="h-10 w-[120px] rounded-xl border-stone-200 bg-white"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {callKindOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={resolutionFilter} onValueChange={(value) => setResolutionFilter(value as ResolutionFilter)}>
                <SelectTrigger className="h-10 w-[132px] rounded-xl border-stone-200 bg-white"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {resolutionOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={imageRouteFilter} onValueChange={(value) => setImageRouteFilter(value as ImageRouteFilter)}>
                <SelectTrigger className="h-10 w-[120px] rounded-xl border-stone-200 bg-white"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {imageRouteOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={errorKindFilter} onValueChange={(value) => setErrorKindFilter(value as ErrorKindFilter)}>
                <SelectTrigger className="h-10 w-[132px] rounded-xl border-stone-200 bg-white"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {errorKindOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </>
          ) : null}
          <Button variant="outline" onClick={clearFilters} className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700">
            清除筛选条件
          </Button>
          <Button onClick={() => void loadLogs()} disabled={isLoading} className="h-10 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800">
            {isLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Search className="size-4" />}
            查询
          </Button>
        </div>
      </div>

      <Card className="overflow-hidden rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="p-0">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-100 px-5 py-4">
            <div className="flex flex-wrap items-center gap-3 text-sm text-stone-600">
              <span>
                共 {filteredItems.length} 条{filteredItems.length !== items.length ? ` / 原始 ${items.length} 条` : ""}
              </span>
              <label className="flex items-center gap-2">
                <Checkbox checked={currentPageSelected} onCheckedChange={(checked) => toggleIds(currentRows.map((item) => item.id), Boolean(checked))} />
                本页全选
              </label>
              <label className="flex items-center gap-2">
                <Checkbox checked={allSelected} onCheckedChange={(checked) => toggleIds(filteredItems.map((item) => item.id), Boolean(checked))} />
                全选结果
              </label>
              {selectedIds.length > 0 ? <span>已选 {selectedIds.length} 条</span> : null}
            </div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" className="h-8 rounded-lg px-3 text-stone-500" onClick={() => void loadLogs()} disabled={isLoading}>
                <RefreshCw className={`size-4 ${isLoading ? "animate-spin" : ""}`} />
                刷新
              </Button>
              <button type="button" className="text-sm text-stone-500 hover:text-stone-900 disabled:text-stone-300" onClick={() => setSelectedIds([])} disabled={selectedIds.length === 0 || isDeleting}>
                取消选择
              </button>
              <Button variant="outline" className="h-8 rounded-lg border-rose-200 bg-white px-3 text-rose-600 hover:bg-rose-50" onClick={() => setDeletingItems(items.filter((item) => selectedSet.has(item.id)))} disabled={selectedIds.length === 0 || isDeleting}>
                <Trash2 className="size-4" />
                删除所选
              </Button>
            </div>
          </div>
          <div className="overflow-x-auto">
            <Table className="min-w-[1120px]">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12"></TableHead>
                  <TableHead>时间</TableHead>
                  <TableHead>类型</TableHead>
                  {isCallLog ? <TableHead>令牌名称</TableHead> : null}
                  {isCallLog ? <TableHead>调用耗时</TableHead> : null}
                  {isCallLog ? <TableHead>状态</TableHead> : null}
                  {isCallLog ? <TableHead className="w-56">标签</TableHead> : null}
                  {isCallLog ? <TableHead className="w-36">图片</TableHead> : null}
                  <TableHead>简述</TableHead>
                  <TableHead className="w-40">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {currentRows.map((item) => {
                  const urls = getUrls(item);
                  const resolution = getResolution(item);
                  const route = getImageRoute(item);
                  const errorKind = getErrorKind(item);
                  const quotaCost = item.detail?.quota_cost;
                  return (
                    <TableRow key={item.id} className="text-stone-600">
                      <TableCell>
                        <Checkbox checked={selectedSet.has(item.id)} onCheckedChange={(checked) => toggleIds([item.id], Boolean(checked))} />
                      </TableCell>
                      <TableCell className="whitespace-nowrap">{item.time}</TableCell>
                      <TableCell><Badge variant="secondary" className="rounded-md">{typeLabels[item.type] || item.type}</Badge></TableCell>
                      {isCallLog ? <TableCell>{getDetailText(item, "key_name")}</TableCell> : null}
                      {isCallLog ? <TableCell>{formatDuration(item)}</TableCell> : null}
                      {isCallLog ? (
                        <TableCell>
                          <Badge variant={item.detail?.status === "failed" ? "danger" : "success"} className="rounded-md">
                            {getStatus(item)}
                          </Badge>
                        </TableCell>
                      ) : null}
                      {isCallLog ? (
                        <TableCell>
                          <div className="flex flex-wrap items-center gap-1.5">
                            {isImageCallLog(item) ? (
                              <>
                                <Badge variant="secondary" className="rounded-md bg-blue-50 text-blue-700">
                                  {resolutionLabel(resolution)}
                                </Badge>
                                <Badge variant="secondary" className="rounded-md bg-stone-100 text-stone-600">
                                  {routeLabel(route)}
                                </Badge>
                                {typeof quotaCost === "number" ? (
                                  <Badge variant="outline" className="rounded-md border-amber-200 bg-amber-50 text-amber-700">
                                    扣 {quotaCost}
                                  </Badge>
                                ) : null}
                              </>
                            ) : (
                              <Badge variant="secondary" className="rounded-md bg-stone-100 text-stone-500">
                                文本
                              </Badge>
                            )}
                            {errorKind !== "none" ? (
                              <Badge variant="danger" className="rounded-md">
                                {errorKindLabel(errorKind)}
                              </Badge>
                            ) : null}
                          </div>
                        </TableCell>
                      ) : null}
                      {isCallLog ? (
                        <TableCell>
                          {urls.length ? (
                            <div className="flex items-center gap-1.5">
                              {urls.slice(0, 3).map((url, imageIndex) => (
                                <button
                                  key={`${url}-${imageIndex}`}
                                  type="button"
                                  className="relative size-9 overflow-hidden rounded-lg border border-stone-200 bg-stone-100"
                                  onClick={() => openLogImage(item, imageIndex)}
                                  title="预览图片"
                                >
                                  <ImageThumbnail src={url} thumbnailSrc={getImageThumbnailUrl(url)} className="h-full w-full" />
                                </button>
                              ))}
                              {urls.length > 3 ? <span className="text-xs text-stone-400">+{urls.length - 3}</span> : null}
                            </div>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-xs text-stone-400">
                              <ImageIcon className="size-3.5" />
                              -
                            </span>
                          )}
                        </TableCell>
                      ) : null}
                      <TableCell className="max-w-[420px] truncate text-stone-500">{item.summary || "-"}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <Button variant="ghost" className="h-8 rounded-lg px-3 text-stone-600" onClick={() => openDetail(item)}>
                            查看详情
                          </Button>
                          <Button variant="ghost" className="h-8 rounded-lg px-3 text-rose-600 hover:bg-rose-50 hover:text-rose-700" onClick={() => setDeletingItems([item])}>
                            删除
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-end gap-2 border-t border-stone-100 px-4 py-3 text-sm text-stone-500">
            <span>第 {safePage} / {pageCount} 页，共 {filteredItems.length} 条</span>
            <Button variant="outline" size="icon" className="size-9 rounded-lg border-stone-200 bg-white" disabled={safePage <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
              <ChevronLeft className="size-4" />
            </Button>
            <Button variant="outline" size="icon" className="size-9 rounded-lg border-stone-200 bg-white" disabled={safePage >= pageCount} onClick={() => setPage((value) => Math.min(pageCount, value + 1))}>
              <ChevronRight className="size-4" />
            </Button>
          </div>
          {!isLoading && filteredItems.length === 0 ? <div className="px-6 py-14 text-center text-sm text-stone-500">没有找到日志</div> : null}
        </CardContent>
      </Card>
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="flex h-[min(88vh,860px)] w-[min(92vw,920px)] flex-col overflow-hidden rounded-2xl p-0">
          <DialogHeader className="shrink-0 border-b border-stone-100 px-6 py-5">
            <DialogTitle>日志详情</DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-y-auto px-6 py-5">
            <div className="space-y-4">
              <div className="grid gap-3 rounded-xl border border-stone-200 bg-white p-4 text-sm text-stone-600 md:grid-cols-2">
                {Object.entries(detailLog?.detail || {})
                  .filter(([key, value]) => key !== "urls" && typeof value !== "object")
                  .map(([key, value]) => (
                    <div key={key} className="flex items-start justify-between gap-4">
                      <span className="text-stone-400">{key}</span>
                      <span className="text-right font-medium break-all text-stone-700">{String(value)}</span>
                    </div>
                  ))}
              </div>
              {detailUrls.length ? (
                <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
                  {detailUrls.map((url, index) => (
                    <button
                      key={url}
                      type="button"
                      className="aspect-square overflow-hidden rounded-xl border border-stone-200 bg-stone-100"
                      onClick={() => {
                        setLightboxIndex(index);
                        setLightboxOpen(true);
                      }}
                    >
                      <img src={url} alt="" className="h-full w-full object-cover" />
                    </button>
                  ))}
                </div>
              ) : null}
              <pre className="max-h-[72vh] overflow-auto rounded-xl border border-stone-200 bg-stone-50 p-4 text-xs leading-6 text-stone-700">
                {JSON.stringify(detailLog?.detail || {}, null, 2)}
              </pre>
            </div>
          </div>
        </DialogContent>
      </Dialog>
      <ImageLightbox
        images={detailImages}
        currentIndex={lightboxIndex}
        open={lightboxOpen}
        onOpenChange={setLightboxOpen}
        onIndexChange={setLightboxIndex}
      />
      <Dialog open={deletingItems.length > 0} onOpenChange={(open) => (!open ? setDeletingItems([]) : null)}>
        <DialogContent showCloseButton={false} className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>{deletingItems.length === 1 ? "删除日志" : "删除所选日志"}</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              确认删除 {deletingItems.length} 条日志吗？删除后无法恢复。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" className="rounded-xl" onClick={() => setDeletingItems([])} disabled={isDeleting}>
              取消
            </Button>
            <Button className="rounded-xl bg-rose-600 text-white hover:bg-rose-700" onClick={() => void confirmDelete()} disabled={isDeleting || deletingItems.length === 0}>
              {isDeleting ? <LoaderCircle className="size-4 animate-spin" /> : null}
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export default function LogsPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);
  if (isCheckingAuth || !session || session.role !== "admin") {
    return <div className="flex min-h-[40vh] items-center justify-center"><LoaderCircle className="size-5 animate-spin text-stone-400" /></div>;
  }
  return <LogsContent />;
}
