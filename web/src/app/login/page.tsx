"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { KeyRound, LoaderCircle, LockKeyhole, UserPlus, UserRound } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { login, loginWithPassword, registerWithPassword } from "@/lib/api";
import { primeAuthSessionCache } from "@/lib/auth-session";
import { useRedirectIfAuthenticated } from "@/lib/use-auth-guard";
import { getDefaultRouteForRole, setStoredAuthSession, type AuthRole } from "@/store/auth";
import { cn } from "@/lib/utils";

type AuthMode = "login" | "register";

function persistSession({
  key,
  role,
  subjectId,
  name,
}: {
  key: string;
  role: AuthRole;
  subjectId: string;
  name: string;
}) {
  const nextSession = { key, role, subjectId, name };
  primeAuthSessionCache(nextSession);
  return setStoredAuthSession(nextSession);
}

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<AuthMode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [authKey, setAuthKey] = useState("");
  const [showKeyLogin, setShowKeyLogin] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { isCheckingAuth } = useRedirectIfAuthenticated();

  const handlePasswordAuth = async () => {
    const normalizedUsername = username.trim();
    if (!normalizedUsername) {
      toast.error("请输入账号");
      return;
    }
    if (!password) {
      toast.error("请输入密码");
      return;
    }
    if (mode === "register") {
      if (password.length < 6) {
        toast.error("密码至少需要 6 个字符");
        return;
      }
      if (password !== confirmPassword) {
        toast.error("两次输入的密码不一致");
        return;
      }
    }

    setIsSubmitting(true);
    try {
      const data =
        mode === "register"
          ? await registerWithPassword(normalizedUsername, password)
          : await loginWithPassword(normalizedUsername, password);
      const sessionKey = String(data.key || "").trim();
      if (!sessionKey) {
        throw new Error("登录成功但没有返回用户密钥，请联系管理员检查账号配置");
      }
      await persistSession({
        key: sessionKey,
        role: data.role,
        subjectId: data.subject_id,
        name: data.name,
      });
      router.replace(getDefaultRouteForRole(data.role));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : mode === "register" ? "注册失败" : "登录失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleKeyLogin = async () => {
    const normalizedAuthKey = authKey.trim();
    if (!normalizedAuthKey) {
      toast.error("请输入密钥");
      return;
    }

    setIsSubmitting(true);
    try {
      const data = await login(normalizedAuthKey);
      await persistSession({
        key: normalizedAuthKey,
        role: data.role,
        subjectId: data.subject_id,
        name: data.name,
      });
      router.replace(getDefaultRouteForRole(data.role));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "登录失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isCheckingAuth) {
    return (
      <div className="grid min-h-[calc(100vh-1rem)] w-full place-items-center px-4 py-6">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return (
    <div className="grid min-h-[calc(100vh-1rem)] w-full place-items-center px-4 py-6">
      <Card className="w-full max-w-[505px] rounded-[24px] border-white/80 bg-white/95 shadow-[0_28px_90px_rgba(28,25,23,0.10)]">
        <CardContent className="space-y-6 p-6 sm:p-8">
          <div className="space-y-4 text-center">
            <div className="mx-auto inline-flex size-14 items-center justify-center rounded-[18px] bg-stone-950 text-white shadow-sm">
              <LockKeyhole className="size-5" />
            </div>
            <div className="space-y-2">
              <h1 className="text-3xl font-semibold tracking-tight text-stone-950">
                {mode === "register" ? "创建账号" : "欢迎回来"}
              </h1>
              <p className="text-sm leading-6 text-stone-500">
                {mode === "register" ? "注册后会自动生成可用的用户密钥。" : "使用账号和密码继续。"}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-1 rounded-2xl border border-stone-200 bg-stone-50 p-1">
            {(
              [
                { value: "login", label: "登录", icon: UserRound },
                { value: "register", label: "注册", icon: UserPlus },
              ] as const
            ).map((item) => {
              const selected = mode === item.value;
              const Icon = item.icon;
              return (
                <button
                  key={item.value}
                  type="button"
                  className={cn(
                    "flex h-11 cursor-pointer items-center justify-center gap-2 rounded-xl text-sm font-medium transition",
                    selected
                      ? "bg-white text-stone-950 shadow-sm ring-1 ring-stone-200"
                      : "text-stone-500 hover:bg-white/70 hover:text-stone-800",
                  )}
                  onClick={() => {
                    setMode(item.value);
                    setShowKeyLogin(false);
                  }}
                >
                  <Icon className="size-4" />
                  {item.label}
                </button>
              );
            })}
          </div>

          <div className="space-y-4">
            <div className="space-y-2">
              <label htmlFor="username" className="block text-sm font-medium text-stone-700">
                账号
              </label>
              <Input
                id="username"
                type="text"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="请输入账号"
                autoComplete="username"
                className="h-12 rounded-2xl border-stone-200 bg-white px-4"
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="password" className="block text-sm font-medium text-stone-700">
                密码
              </label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && mode === "login") {
                    void handlePasswordAuth();
                  }
                }}
                placeholder="请输入密码"
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                className="h-12 rounded-2xl border-stone-200 bg-white px-4"
              />
            </div>
            {mode === "register" ? (
              <div className="space-y-2">
                <label htmlFor="confirm-password" className="block text-sm font-medium text-stone-700">
                  确认密码
                </label>
                <Input
                  id="confirm-password"
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      void handlePasswordAuth();
                    }
                  }}
                  placeholder="再次输入密码"
                  autoComplete="new-password"
                  className="h-12 rounded-2xl border-stone-200 bg-white px-4"
                />
              </div>
            ) : null}
          </div>

          <Button
            className="h-12 w-full rounded-2xl bg-stone-950 text-white hover:bg-stone-800"
            onClick={() => void handlePasswordAuth()}
            disabled={isSubmitting}
          >
            {isSubmitting ? (
              <LoaderCircle className="size-4 animate-spin" />
            ) : mode === "register" ? (
              <UserPlus className="size-4" />
            ) : (
              <UserRound className="size-4" />
            )}
            {mode === "register" ? "注册并登录" : "登录"}
          </Button>

          <div className="border-t border-stone-100 pt-4">
            {showKeyLogin ? (
              <div className="space-y-3">
                <div className="space-y-2">
                  <label htmlFor="auth-key" className="block text-sm font-medium text-stone-700">
                    密钥
                  </label>
                  <Input
                    id="auth-key"
                    type="password"
                    value={authKey}
                    onChange={(event) => setAuthKey(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        void handleKeyLogin();
                      }
                    }}
                    placeholder="管理员密钥或用户密钥"
                    className="h-11 rounded-2xl border-stone-200 bg-white px-4"
                  />
                </div>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    className="h-10 flex-1 rounded-xl border-stone-200 bg-white"
                    onClick={() => setShowKeyLogin(false)}
                    disabled={isSubmitting}
                  >
                    返回
                  </Button>
                  <Button
                    type="button"
                    className="h-10 flex-1 rounded-xl bg-stone-950 text-white hover:bg-stone-800"
                    onClick={() => void handleKeyLogin()}
                    disabled={isSubmitting}
                  >
                    {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : <KeyRound className="size-4" />}
                    密钥登录
                  </Button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                className="mx-auto flex cursor-pointer items-center gap-1.5 text-xs font-medium text-stone-400 transition hover:text-stone-700"
                onClick={() => setShowKeyLogin(true)}
              >
                <KeyRound className="size-3.5" />
                使用密钥登录
              </button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
