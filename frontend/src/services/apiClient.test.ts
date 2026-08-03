import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { storeSession, clearSession } from "../auth/session";
import { ApiError, apiClient, setUnauthorizedHandler } from "../services/apiClient";
import { futureExpiresAt } from "../test/fixtures";

describe("apiClient", () => {
  beforeEach(() => {
    clearSession();
    setUnauthorizedHandler(null);
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setUnauthorizedHandler(null);
  });

  it("attaches bearer token and parses JSON success", async () => {
    storeSession("abc.token", futureExpiresAt());
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: 1, username: "admin", is_active: true, authenticated: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    const session = await apiClient.getSession();

    expect(session.username).toBe("admin");
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/auth/me");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer abc.token");
  });

  it("throws ApiError with detail message on failure", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "Credenziali non valide" }), {
        status: 401,
        headers: { "Content-Type": "application/json" }
      })
    );

    await expect(apiClient.login("admin", "wrong")).rejects.toMatchObject({
      name: "ApiError",
      message: "Credenziali non valide",
      status: 401
    } satisfies Partial<ApiError>);
  });

  it("invokes unauthorized handler on 401", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "expired" }), {
        status: 401,
        headers: { "Content-Type": "application/json" }
      })
    );

    await expect(apiClient.getSession()).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("falls back to HTTP status when body is not JSON", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue(new Response("plain error", { status: 502 }));

    await expect(apiClient.getImportStatus()).rejects.toMatchObject({
      message: "HTTP 502",
      status: 502
    });
  });

  it("builds query strings for list endpoints", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 50 }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await apiClient.getUpcomingPredictions({
      model_version: "v3",
      model_name: "logistic_regression",
      status: "upcoming",
      limit: 50
    });

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe("/api/next-fixtures/predictions");
    expect(parsed.searchParams.get("model_version")).toBe("v3");
    expect(parsed.searchParams.get("model_name")).toBe("logistic_regression");
    expect(parsed.searchParams.get("status")).toBe("upcoming");
    expect(parsed.searchParams.get("limit")).toBe("50");
  });

  it("posts payment checkout payload", async () => {
    storeSession("abc.token", futureExpiresAt());
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          provider: "stripe",
          mode: "sandbox",
          idempotency_key: "idem-payment-0001",
          checkout_url: "https://checkout.stripe.test/idem-payment-0001",
          session_id: "cs_test_123",
          customer_id: "cus_test_123",
          plan_code: "pro",
          billing_cycle: "monthly",
          expires_at: null,
          reused: false
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" }
        }
      )
    );

    await apiClient.createPaymentCheckout({
      telegram_user_id: 123,
      username: "alice",
      plan_code: "pro",
      billing_cycle: "monthly",
      idempotency_key: "idem-payment-0001"
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/payments/checkout");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer abc.token");
    expect(init?.body).toBe(
      JSON.stringify({
        telegram_user_id: 123,
        username: "alice",
        plan_code: "pro",
        billing_cycle: "monthly",
        idempotency_key: "idem-payment-0001"
      })
    );
  });

  it("downloads subscriptions dashboard CSV", async () => {
    storeSession("abc.token", futureExpiresAt());
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue(
      new Response("user_id,username\n1,alice\n", {
        status: 200,
        headers: {
          "Content-Type": "text/csv",
          "Content-Disposition": "attachment; filename=\"subscriptions_dashboard.csv\""
        }
      })
    );

    const file = await apiClient.exportSubscriptionsDashboardCsv({ plan_code: "pro" });

    expect(file.filename).toBe("subscriptions_dashboard.csv");
    expect(await file.blob.text()).toContain("user_id,username");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/subscriptions/dashboard/export.csv");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer abc.token");
  });
});
