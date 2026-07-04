"""
ai_bias.py
تحلیل بایاس ماکرو روزانه با پشتیبانی از چندین provider.

روند کار:
  1. اگر برای امروز قبلاً بایاس گرفته‌ایم (cache)، همان را برمی‌گردانیم.
  2. در غیر این صورت provider اصلی (primary) صدا زده می‌شود.
  3. اگر primary شکست خورد (network/parse)، provider جایگزین (fallback) تلاش می‌کند.
  4. پاسخ را به‌صورت JSON پارس می‌کنیم و در cache ذخیره می‌کنیم.
  5. در صورت بروز خطا، بایاس "NEUTRAL" برمی‌گردد تا ربات متوقف نشود.
  6. ارسال خودکار بایاس به تلگرام پس از دریافت موفقیت‌آمیز.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Provider Configuration
# ─────────────────────────────────────────────
VALID_BIASES = {"BULLISH", "BEARISH", "NEUTRAL"}

SYSTEM_PROMPT = (
    "You are a senior macro economic analyst specialized in currency and "
    "commodity markets. Your role is to determine today's directional bias "
    "for trading decisions.\n\n"
    "CRITICAL OUTPUT RULES:\n"
    "  1. Output ONLY a JSON object. No greeting, no preamble, no explanation.\n"
    "  2. Start your response with '{' and end with '}'.\n"
    "  3. Keep the reasoning field to ONE short sentence (max 20 words).\n"
    "  4. Keep key_drivers to at most 3 items, each max 6 words.\n"
    "  Be extremely concise to fit within the token budget."
)

USER_PROMPT_TEMPLATE = (
    "Based on the current macroeconomic environment and the US Dollar (DXY), "
    "determine today's market bias for {symbol}.\n\n"
    "Consider these factors in your analysis:\n"
    "  - US Dollar strength/weakness (DXY)\n"
    "  - Fed monetary policy stance and recent statements\n"
    "  - Inflation data (CPI, PCE) and employment (NFP)\n"
    "  - Geopolitical tensions and risk sentiment\n"
    "  - Safe-haven flows (Gold, JPY, CHF)\n\n"
    "Respond ONLY with this exact JSON structure (no markdown, no extra text):\n"
    "{{\n"
    "  \"bias\": \"BULLISH\" | \"BEARISH\" | \"NEUTRAL\",\n"
    "  \"confidence\": <integer 0-100>,\n"
    "  \"reasoning\": \"<one short sentence>\",\n"
    "  \"key_drivers\": [\"<driver1>\", \"<driver2>\"]\n"
    "}}\n\n"
    "Rules:\n"
    "  - bias MUST be exactly one of: BULLISH, BEARISH, NEUTRAL\n"
    "  - confidence MUST be an integer between 0 and 100\n"
    "  - Do NOT include any text outside the JSON object.\n"
    "  - Do NOT wrap the JSON in markdown code fences."
)


@dataclass
class Provider:
    """پیکربندی یک provider AI."""
    name: str
    api_key: str
    base_url: str
    model: str
    headers: dict = field(default_factory=dict)
    is_fallback: bool = False

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


class AIBiasAnalyzer:
    """تحلیل‌گر بایاس ماکرو با primary + fallback providers."""

    def __init__(self,
                 symbol: str = config.SYMBOL,
                 primary_name: str = config.AI_PRIMARY_PROVIDER,
                 fallback_name: str = config.AI_FALLBACK_PROVIDER,
                 telegram=None):
        self.symbol = symbol
        self.providers = self._build_providers(primary_name, fallback_name)
        self._cache: dict = {}
        self.telegram = telegram  # TelegramNotifier instance

    def _build_providers(self, primary_name: str, fallback_name: str) -> list:
        """ساخت لیست providerها (primary اول، fallback بعد)."""
        providers = []

        # ── Primary ──
        if primary_name == "gemini":
            providers.append(Provider(
                name="gemini",
                api_key=config.GEMINI_API_KEY,
                base_url=config.GEMINI_BASE_URL,
                model=config.GEMINI_MODEL,
                headers={"Authorization": f"Bearer {config.GEMINI_API_KEY}"},
            ))
        elif primary_name == "openrouter":
            providers.append(Provider(
                name="openrouter",
                api_key=config.OPENROUTER_API_KEY,
                base_url=config.OPENROUTER_BASE_URL,
                model=config.OPENROUTER_MODEL,
                headers={
                    "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/Areuoko/bot-trader-z",
                    "X-Title": "Bot Trader Z",
                },
            ))
        else:
            logger.warning("Unknown primary provider '%s'. Using openrouter.", primary_name)
            providers.append(Provider(
                name="openrouter",
                api_key=config.OPENROUTER_API_KEY,
                base_url=config.OPENROUTER_BASE_URL,
                model=config.OPENROUTER_MODEL,
                headers={
                    "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/Areuoko/bot-trader-z",
                    "X-Title": "Bot Trader Z",
                },
            ))

        # ── Fallback ──
        if fallback_name == "gemini":
            fb = Provider(
                name="gemini",
                api_key=config.GEMINI_API_KEY,
                base_url=config.GEMINI_BASE_URL,
                model=config.GEMINI_MODEL,
                headers={"Authorization": f"Bearer {config.GEMINI_API_KEY}"},
                is_fallback=True,
            )
        else:
            fb = Provider(
                name="openrouter",
                api_key=config.OPENROUTER_API_KEY,
                base_url=config.OPENROUTER_BASE_URL,
                model=config.OPENROUTER_MODEL,
                headers={
                    "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/Areuoko/bot-trader-z",
                    "X-Title": "Bot Trader Z",
                },
                is_fallback=True,
            )

        # از افزودن duplicate جلوگیری کن (بررسی از روی لیست محلی، نه self)
        if fb.name != providers[0].name or fb.model != providers[0].model:
            providers.append(fb)
        else:
            logger.info("Fallback provider is identical to primary; using primary only.")

        return providers

    # ─────────────────────────────────────────────
    # Cache Management (daily)
    # ─────────────────────────────────────────────
    def _today_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load_cache(self) -> dict:
        try:
            with open(config.BIAS_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load bias cache: %s", e)
            return {}

    def _save_cache(self, cache: dict) -> None:
        try:
            with open(config.BIAS_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warning("Failed to save bias cache: %s", e)

    def _get_cached(self) -> Optional[dict]:
        today = self._today_key()
        cache = self._load_cache()
        if today in cache:
            logger.info("Bias cache HIT for %s.", today)
            return cache[today]
        return None

    def _store_cache(self, bias_data: dict) -> None:
        today = self._today_key()
        cache = self._load_cache()
        cache[today] = bias_data
        self._save_cache(cache)

    # ─────────────────────────────────────────────
    # AI API Call
    # ─────────────────────────────────────────────
    def _call_provider(self, provider: Provider, user_prompt: str) -> Optional[str]:
        """
        یک تلاش با یک provider خاص.
        اگر جواب Parse-friendly نبود، return None.
        """
        if not provider.is_configured:
            logger.warning("Provider %s is not configured (missing key/url/model).",
                           provider.name)
            return None

        payload = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": config.AI_TEMPERATURE,
            "max_tokens": config.AI_MAX_TOKENS,
        }

        # برای Gemini، model معمولاً از URL شناخته می‌شود، ولی در body هم می‌فرستیم.
        headers = provider.headers.copy()
        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

        last_err = None
        for attempt in range(1, config.AI_MAX_RETRIES + 1):
            try:
                label = "fallback" if provider.is_fallback else "primary"
                logger.info("[%s/%s] AI call attempt %d/%d -> %s (%s)",
                            label, provider.name, attempt,
                            config.AI_MAX_RETRIES, provider.model, provider.base_url)
                resp = requests.post(
                    provider.base_url,
                    headers=headers,
                    json=payload,
                    timeout=config.AI_TIMEOUT,
                )

                # 401/403 = کلید مشکل داره → سریع برو fallback
                if resp.status_code in (401, 403):
                    logger.error("Provider %s auth failed (HTTP %d): %s",
                                 provider.name, resp.status_code, resp.text[:200])
                    return None

                if resp.status_code != 200:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    logger.warning("Provider %s HTTP error attempt %d: %s",
                                   provider.name, attempt, last_err)
                    continue

                data = resp.json()
                content = data["choices"][0]["message"]["content"]

                # اگر finish_reason=length یعنی truncated
                finish_reason = data["choices"][0].get("finish_reason")
                if finish_reason == "length":
                    logger.warning("Provider %s response was truncated (max_tokens). "
                                   "Will attempt rescue parser.", provider.name)

                logger.info("Provider %s response received (%d tokens approx).",
                            provider.name, len(content.split()))
                return content

            except requests.exceptions.RequestException as e:
                last_err = str(e)
                logger.warning("Provider %s network error attempt %d: %s",
                               provider.name, attempt, last_err)
            except (KeyError, json.JSONDecodeError) as e:
                last_err = str(e)
                logger.warning("Provider %s response error attempt %d: %s",
                               provider.name, attempt, last_err)

        logger.error("Provider %s failed after %d retries. Last error: %s",
                     provider.name, config.AI_MAX_RETRIES, last_err)
        return None

    # ─────────────────────────────────────────────
    # Response Parsing
    # ─────────────────────────────────────────────
    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """
        استخراج JSON از پاسخ مدل. مقاوم در برابر:
          - JSON خالص
          - JSON محصور در markdown fences ```json ... ```
          - JSON با متن اضافی قبل/بعد
          - JSON بریده‌شده (truncated)
        """
        # تلاش ۱: پارس مستقیم
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # تلاش 2: حذف markdown fences
        fence_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
        match = re.search(fence_pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # تلاش 3: اولین {...} در متن
        brace_pattern = r"\{.*\}"
        match = re.search(brace_pattern, text, re.DOTALL)
        if match:
            candidate = match.group(0)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        # تلاش 4: نجات JSON بریده‌شده
        rescued = AIBiasAnalyzer._rescue_truncated_json(text)
        if rescued is not None:
            logger.warning("AI response was truncated. Rescued partial JSON: %s",
                           list(rescued.keys()))
            return rescued

        logger.error("Could not parse JSON from AI response. Raw: %s", text[:300])
        return None

    @staticmethod
    def _rescue_truncated_json(text: str) -> Optional[dict]:
        """نجات فیلدهای موجود از یک JSON بریده‌شده."""
        start = text.find("{")
        if start == -1:
            return None
        pattern = r'"(\w+)"\s*:\s*("(?:[^"\\]|\\.)*"|\d+(?:\.\d+)?)'
        matches = re.findall(pattern, text[start:])
        if not matches:
            return None
        result = {}
        for key, val in matches:
            if val.startswith('"'):
                result[key] = val[1:-1]
            else:
                try:
                    result[key] = float(val) if '.' in val else int(val)
                except ValueError:
                    result[key] = val
        if "bias" not in result:
            return None
        return result

    def _validate_bias(self, data: dict, provider_name: str) -> dict:
        """اعتبارسنجی و نرمال‌سازی خروجی مدل."""
        bias = str(data.get("bias", "")).upper().strip()
        if bias not in VALID_BIASES:
            logger.warning("Invalid bias '%s' from %s, defaulting to NEUTRAL.",
                           bias, provider_name)
            bias = "NEUTRAL"

        try:
            confidence = int(data.get("confidence", 0))
            confidence = max(0, min(100, confidence))
        except (ValueError, TypeError):
            confidence = 0
            logger.warning("Invalid confidence, defaulting to 0.")

        reasoning = str(data.get("reasoning", "No reasoning provided."))[:300]
        drivers = data.get("key_drivers", [])
        if not isinstance(drivers, list):
            drivers = [str(drivers)]
        drivers = [str(d)[:100] for d in drivers][:5]

        return {
            "bias": bias,
            "confidence": confidence,
            "reasoning": reasoning,
            "key_drivers": drivers,
            "provider": provider_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────
    def get_daily_bias(self) -> dict:
        """
        بایاس ماکرو امروز را برمی‌گرداند.
        ابتدا cache، سپس primary provider، سپس fallback provider.
        در صورت دریافت بایاس جدید، به تلگرام ارسال می‌شود.
        """
        # 1. Cache
        cached = self._get_cached()
        if cached is not None:
            return cached

        # 2. اگر هیچ provider پیکربندی نشده
        if not any(p.is_configured for p in self.providers):
            logger.warning("No AI provider configured. Returning NEUTRAL bias.")
            return self._validate_bias({"bias": "NEUTRAL"}, "none")

        # 3. امتحان کردن providerها
        user_prompt = USER_PROMPT_TEMPLATE.format(symbol=self.symbol)
        used_provider = None
        raw_text = None

        for provider in self.providers:
            raw_text = self._call_provider(provider, user_prompt)
            if raw_text is not None:
                used_provider = provider.name
                break
            logger.info("Switching from %s to next provider...", provider.name)

        # 4. Parse + Validate
        if raw_text is None:
            logger.warning("All AI providers failed, defaulting to NEUTRAL bias.")
            return self._validate_bias({"bias": "NEUTRAL"}, "none")

        parsed = self._extract_json(raw_text)
        if parsed is None:
            logger.warning("Could not parse AI response, defaulting to NEUTRAL.")
            return self._validate_bias({"bias": "NEUTRAL"}, used_provider or "none")

        final = self._validate_bias(parsed, used_provider or "unknown")

        # 5. Store cache
        self._store_cache(final)
        logger.info("Daily bias stored: %s (confidence=%d%%) via %s",
                    final["bias"], final["confidence"], final["provider"])

        # 6. Send to Telegram
        self._send_bias_to_telegram(final)

        return final

    def _send_bias_to_telegram(self, bias_data: dict) -> None:
        """ارسال بایاس روزانه به تلگرام."""
        if not self.telegram:
            return
        try:
            bias_text = (
                f"📊 <b>بایاس روزانه:</b> {bias_data.get('bias', 'NEUTRAL')}\n"
                f"🎯 <b>اعتماد:</b> {bias_data.get('confidence', 0)}%\n"
                f"💡 <b>دلیل:</b> {bias_data.get('reasoning', 'N/A')}\n"
                f"🔑 <b>عوامل کلیدی:</b>\n"
            )
            for driver in bias_data.get("key_drivers", []):
                bias_text += f"  • {driver}\n"
            self.telegram.send_daily_ai_bias(bias_text)
        except Exception as e:
            logger.warning("Failed to send Telegram daily bias notification: %s", e)


# ─────────────────────────────────────────────
# Smoke test — python ai_bias.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    analyzer = AIBiasAnalyzer()
    print("\n=== Getting daily bias ===")
    result = analyzer.get_daily_bias()
    print(json.dumps(result, indent=2, ensure_ascii=False))
