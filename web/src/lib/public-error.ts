export function publicErrorMessage(value: unknown) {
  const message = value instanceof Error ? value.message : String(value || "");
  const text = message.trim();
  const lower = text.toLowerCase();
  if (!text) return "请求失败，请稍后重试";

  if (text.includes("请先兑换额度后使用")) return text;
  if (text.includes("当前用户权限") || text.includes("密钥无效") || text.includes("重新登录")) return text;
  if (text.includes("额度不足") || lower.includes("insufficient_quota")) return "额度不足，请兑换后继续使用";
  if (lower.includes("prompt is required")) return "请输入提示词";
  if (lower.includes("image file is required") || lower.includes("image is required")) return "请上传参考图后重试";
  if (lower.includes("image file is empty")) return "参考图读取失败，请重新上传";

  if (
    lower.includes("content_policy") ||
    lower.includes("content policy") ||
    lower.includes("policy violation") ||
    lower.includes("safety") ||
    lower.includes("blocked") ||
    lower.includes("rejected") ||
    lower.includes("sensitive") ||
    text.includes("AI 审核未通过") ||
    text.includes("检测到敏感词")
  ) {
    return "提示词可能不符合规则，请调整后重试";
  }

  if (
    lower.includes("no available image quota") ||
    lower.includes("no available codex image quota") ||
    lower.includes("free plan limit") ||
    lower.includes("usage_limit_reached") ||
    lower.includes("rate_limit_exceeded") ||
    lower.includes("too many requests") ||
    text.includes("账号生图额度已用完") ||
    text.includes("限流")
  ) {
    return "账号池暂时限流或额度不足，请稍后重试";
  }

  if (
    lower.includes("proxy error") ||
    lower.includes("proxy connection") ||
    lower.includes("tunnel connection") ||
    lower.includes("socks") ||
    lower.includes("curl: (77)") ||
    lower.includes("certificate verify") ||
    lower.includes("certificate verify locations") ||
    lower.includes("ca cert")
  ) {
    return "代理连接异常，请切换节点后重试";
  }

  if (
    text.includes("高清中转接口调用失败") ||
    text.includes("中转接口调用失败") ||
    lower.includes("duck:") ||
    lower.includes("und_err_socket") ||
    lower.includes("econnreset") ||
    lower.includes("socket hang up") ||
    lower.includes("socketerror") ||
    lower.includes("remote disconnected") ||
    lower.includes("remotedisconnected") ||
    lower.includes("connection closed") ||
    lower.includes("connection aborted") ||
    lower.includes("connection reset") ||
    lower.includes("fetch failed") ||
    lower.includes("failed to fetch") ||
    lower.includes("network error") ||
    lower.includes("curl:") ||
    lower.includes("timeout") ||
    lower.includes("timed out") ||
    lower.includes("status_code=500") ||
    lower.includes("http 500") ||
    lower.includes("traceid:") ||
    lower.includes("request id:") ||
    lower.includes("upstream image connection failed") ||
    lower.includes("failed to perform")
  ) {
    if (text.includes("中转") || lower.includes("duck:")) {
      return "中转接口连接失败，请稍后重试或切换代理节点";
    }
    return "接口繁忙，请稍后重试";
  }

  return text;
}
