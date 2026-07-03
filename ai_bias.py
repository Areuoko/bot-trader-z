"""
ai_bias.py
تحلیل بایاس ماکرو روزانه با استفاده از مدل هوش مصنوعی از طریق OpenRouter.

روند کار:
  1. اگر برای امروز قبلاً بایاس گرفته‌ایم (cache)، همان را برمی‌گردانیم.
  2. در غیر این صورت پرامپت ساختاریافته‌ای به مدل می‌فرستیم.
  3. پاسخ را به‌صورت JSON پارس می‌کنیم و در cache ذخیره می‌کنیم.
  4. در صورت بروز خطا، بایاس "NEUTRAL" برمی‌گردد تا ربات متوقف نشود.
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Constants
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


class AIBiasAnalyzer:
    """تحلیل‌گر بایاس ماکرو با اتصال به OpenRouter."""

    def __init__(self,
                 api_key: str = config.AI_API_KEY,
                 base_url: str = config.AI_BASE_URL,
                 model: str = config.AI_MODEL,
                 symbol: str = config.SYMBOL):
        if not api_key:
            logger.warning(
                "AI_API_KEY is empty! Bias analysis will default to NEUTRAL. "
                "Set it in .env file."
            )
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.symbol = symbol
        self._cache: dict = {}

    # ─────────────────────────────────────────────
    # Cache Management (daily)
    # ─────────────────────────────────────────────
    def _today_key(self) -> str:
        """کلید تاریخ امروز به فرمت YYYY-MM-DD در UTC."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load_cache(self) -> dict:
        """بارگذاری cache از فایل محلی در صورت وجود."""
        try:
            with open(config.BIAS_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load bias cache: %s", e)
            return {}

    def _save_cache(self, cache: dict) -> None:
        """ذخیره cache در فایل محلی."""
        try:
            with open(config.BIAS_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warning("Failed to save bias cache: %s", e)

    def _get_cached(self) -> Optional[dict]:
        """بایاس امروز را از cache برمی‌گرداند یا None."""
        today = self._today_key()
        cache = self._load_cache()
        if today in cache:
            logger.info("Bias cache HIT for %s.", today)
            return cache[today]
        return None

    def _store_cache(self, bias_data: dict) -> None:
        """بایاس امروز را در cache ذخیره می‌کند."""
        today = self._today_key()
        cache = self._load_cache()
        cache[today] = bias_data
        self._save_cache(cache)

    # ─────────────────────────────────────────────
    # AI API Call
    # ─────────────────────────────────────────────
    def _call_api(self, user_prompt: str) -> Optional[str]:
        """
        ارسال درخواست به OpenRouter و دریافت پاسخ متنی مدل.
        در صورت خطای شبکه، retry می‌شود.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # OpenRouter برای رتبه‌بندی مدل‌ها این هدرها را توصیه می‌کند
            "HTTP-Referer": "https://github.com/Areuoko/bot-trader-z",
            "X-Title": "Bot Trader Z",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": config.AI_TEMPERATURE,
            "max_tokens": config.AI_MAX_TOKENS,
        }

        last_err = None
        for attempt in range(1, config.AI_MAX_RETRIES + 1):
            try:
                logger.info("AI API call attempt %d/%d...", attempt, config.AI_MAX_RETRIES)
                resp = requests.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=config.AI_TIMEOUT,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    logger.info("AI response received (%d tokens approx).",
                                len(content.split()))
                    return content
                else:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    logger.warning("API error attempt %d: %s", attempt, last_err)
            except requests.exceptions.RequestException as e:
                last_err = str(e)
                logger.warning("Network error attempt %d: %s", attempt, last_err)

        logger.error("All AI API retries exhausted. Last error: %s", last_err)
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
          - JSON بریده‌شده (truncated) ← نجات‌دهنده
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

        # تلاش 4: نجات JSON بریده‌شده (truncated)
        # اگر JSON از '}' آخر باز موند، می‌توانیم فیلدهای موجود را استخراج کنیم.
        rescued = AIBiasAnalyzer._rescue_truncated_json(text)
        if rescued is not None:
            logger.warning("AI response was truncated. Rescued partial JSON: %s",
                           list(rescued.keys()))
            return rescued

        logger.error("Could not parse JSON from AI response. Raw: %s", text[:300])
        return None

    @staticmethod
    def _rescue_truncated_json(text: str) -> Optional[dict]:
        """
        نجات فیلدهای موجود از یک JSON بریده‌شده.

        مثال:
          '{"bias": "BULLISH", "confidence": 75, "reasoning": "Geopol...'
          → {"bias": "BULLISH", "confidence": 75}

        فقط فیلدهای پرانتز/کاما-دار کامل شده استخراج می‌شوند.
        """
        # پیدا کردن اولین '{'
        start = text.find("{")
        if start == -1:
            return None
        # استخراج key-value pairs با regex
        pattern = r'"(\w+)"\s*:\s*("(?:[^"\\]|\\.)*"|\d+(?:\.\d+)?)'
        matches = re.findall(pattern, text[start:])
        if not matches:
            return None
        result = {}
        for key, val in matches:
            # اگر مقدار رشته‌ای است، کوتیشن‌ها را حذف کن
            if val.startswith('"'):
                result[key] = val[1:-1]
            else:
                try:
                    result[key] = float(val) if '.' in val else int(val)
                except ValueError:
                    result[key] = val
        # فقط اگر حداقل bias وجود داشت معتبر است
        if "bias" not in result:
            return None
        return result

    def _validate_bias(self, data: dict) -> dict:
        """
        اعتبارسنجی و نرمال‌سازی خروجی مدل.
        مقادیر نامعتبر را به مقادیر امن تبدیل می‌کند.
        """
        bias = str(data.get("bias", "")).upper().strip()
        if bias not in VALID_BIASES:
            logger.warning("Invalid bias '%s' from model, defaulting to NEUTRAL.", bias)
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
            "model": self.model,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────
    def get_daily_bias(self) -> dict:
        """
        بایاس ماکرو امروز را برمی‌گرداند.

        روند:
          1. اول cache امروز را چک کن.
          2. اگر نبود، API صدا بزن.
          3. پاسخ را parse و validate کن.
          4. در cache ذخیره کن.
          5. در صورت خطا، NEUTRAL برگردان.

        Returns:
            dict with keys: bias, confidence, reasoning, key_drivers,
                            model, timestamp
        """
        # 1. Cache
        cached = self._get_cached()
        if cached is not None:
            return cached

        # 2. اگر API key نباشد، فوراً NEUTRAL برگردان
        if not self.api_key:
            logger.warning("No API key. Returning NEUTRAL bias.")
            return self._validate_bias({})

        # 3. API call
        user_prompt = USER_PROMPT_TEMPLATE.format(symbol=self.symbol)
        raw_text = self._call_api(user_prompt)
        if raw_text is None:
            logger.warning("AI call failed, defaulting to NEUTRAL bias.")
            return self._validate_bias({})

        # 4. Parse + Validate
        parsed = self._extract_json(raw_text)
        if parsed is None:
            logger.warning("Could not parse AI response, defaulting to NEUTRAL.")
            return self._validate_bias({})

        final = self._validate_bias(parsed)

        # 5. Store in cache
        self._store_cache(final)
        logger.info("Daily bias stored: %s (confidence=%d%%)",
                    final["bias"], final["confidence"])
        return final


# ─────────────────────────────────────────────
# Smoke test — python ai_bias.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    analyzer = AIBiasAnalyzer()
    print("\n=== Getting daily bias ===")
    result = analyzer.get_daily_bias()
    print(json.dumps(result, indent=2, ensure_ascii=False))
