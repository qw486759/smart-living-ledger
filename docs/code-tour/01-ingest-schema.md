# Code Tour 第 1 站：`ingest/schema.py`

系統的「入境海關」：所有進入平台的事件都必須先過這關；不合格就在這裡擋掉
（丟出 `ValidationError` → ingest handler 把它轉成 HTTP 400）。核心思想：
**在邊界一次驗好，後面每一支 Lambda 就能安心信任資料的形狀。**

這是一個**純驗證層**——不碰 AWS、不改資料，只回答「這是不是一個合法事件」。
以下行號對應目前（重構後）的檔案，跟你本地讀的一致。

---

## 區塊 1 — 檔頭與 import（L1–4）

```python
from __future__ import annotations   # L1
import time                          # L3
from typing import Any               # L4
```

- **L1** — 讓型別註解（如 `dict[str, Any]`）以字串形式延後求值；較快，也讓新語法在舊 Python 相容。
- **L3** — `time` 用來檢查 `ts` 是否太未來／太舊。
- **L4** — `Any` = 「任何型別」，給註解用。

## 區塊 2 — 常數（L6–17）

```python
VALID_TYPES = {"motion","plug","temp","voice","sighting","feeding","intrusion"}   # L6
VALID_VOICE_COMMANDS = {"turn on lights","set temperature","status check"}        # L7
MAX_CLOCK_SKEW_SECONDS = 300      # L8
MAX_EVENT_AGE_SECONDS = 30 * 86400  # L12（30 天的秒數）
SIGHTING_MIN_CONFIDENCE = 0.0     # L15
SIGHTING_MAX_CONFIDENCE = 1.0     # L16
FEEDING_MAX_GRAMS = 2000.0        # L17
```

- **L6** — 合法事件型別，用 **`set`** 是因為 `in` 判斷是 O(1)。
- **L7** — 只接受這三個 voice 指令（舊智慧家庭 demo 用）。
- **L8** — 允許事件時間比現在最多**未來 5 分鐘**（裝置時鐘會有偏差）。
- **L9–12** — 拒收超過 **30 天**的舊事件；註解點明這跟 DynamoDB TTL（`expire_at ≈ 30 天`）
  呼應，避免存進一筆馬上就會被 TTL 刪掉的資料。
- **L15–16** — confidence 必須落在 `[0, 1]`。
- **L17** — 進食克數上限，用來擋明顯壞掉的資料。

## 區塊 3 — 自訂例外（L20–21）

```python
class ValidationError(ValueError):   # L20
    pass                             # L21
```

**繼承 `ValueError`**，所以呼叫端可以精準 catch `ValidationError`，也能用寬鬆的
`except ValueError` 接到。ingest handler 靠它把「使用者輸入錯」對映成 HTTP 400。
`pass` = 不需要額外行為，只是需要這個獨立的「型別標籤」。

## 區塊 4 — 總入口 `validate_event`（L24–42）

```python
def validate_event(data):                                     # L24
    if not isinstance(data, dict): raise ValidationError(...)  # L25–26
    _require_str(data, "device_id")                            # L28
    _require_str(data, "type")                                 # L29
    _require_int(data, "ts", min_value=1)                      # L30
    event_type = data["type"]                                  # L32
    if event_type not in VALID_TYPES: raise ...                # L33–35
    payload = data.get("payload")                              # L37
    if not isinstance(payload, dict): raise ...                # L38–39
    VALIDATORS[event_type](payload)                            # L41
    return data                                                # L42
```

- **L25–26** — body 必須是 JSON 物件。
- **L28–30** — 先驗每種事件都必備的共同欄位（device_id、type、ts）。
- **L33–35** — type 必須在白名單內；錯誤訊息會**列出所有合法值**（排序後），讓呼叫端知道能填什麼。
- **L37–39** — payload 必須存在且是物件。`.get` 不會 `KeyError`，取不到就是 `None`，被這行擋下。
- **L41** — 分派的精髓：用 type 去 `VALIDATORS` 查表，呼叫對應的驗證器。
- **L42** — 原封不動回傳 data。**驗證只檢查、不轉換**（float→Decimal 的轉型在後面的 handler 做，關注點分離）。

## 區塊 5 — 各型別驗證器（L45–171）

每個都同一個模式：取欄位 → 檢查型別 → 檢查範圍 → 錯就丟明確訊息。各自的「為什麼」：

- **`_validate_motion`（L45–47）** — `detected` 必須是 bool。
- **`_validate_plug`（L50–57）** — `watt` 是數字且 0–2400（斷路器額定）。
- **`_validate_temp`（L60–76）** — `celsius` 數字 −50..100、`humidity` 數字 0..100。
- **`_validate_voice`（L79–87）** — `command` 是字串且在合法集合內。
  *（motion / plug / temp / voice 是舊智慧家庭型別——見文末「Parked 決定」。）*
- **`_require_zone_source_confidence`（L90–107）** — review 時抽出的共用 helper，
  給觀察類型別用：非空 `zone`、非空 `source`、`confidence` 是數字且在 `[0,1]`。
  `kind` 參數讓錯誤訊息能顯示是 "sighting" 還是 "intrusion"，同一份實作服務兩種型別。
- **`_validate_sighting`（L110–132）** — 先呼叫共用 helper，再驗：
  `animal_count` **選填**（若有則 int ≥ 1）、`others_present` **選填** bool。
- **`_validate_intrusion`（L135–149）** — 先呼叫共用 helper，再驗
  `animal_count` **必填**（定義上一定有動物）、int ≥ 1。
- **`_validate_feeding`（L152–171）** — `grams` 必填 0–2000；`duration_s` 選填數字 ≥ 0。

## 區塊 6 — dispatch 表（L174–184）

```python
VALIDATORS = { "motion": _validate_motion, ..., "intrusion": _validate_intrusion }  # L176–184
```

type → 驗證器的對照表，**module 載入時建一次**（review 時從 `validate_event` 內搬出來，
因為它從不改變）。它定義在所有 `_validate_*` 函式**之後**——因為 dict 要引用那些函式，
必須它們先存在。

## 區塊 7 — 底層 helpers（L187–214）

- **`_require_str`（L187–190）** — 值必須是字串，且 `strip()` 後非空（擋空字串／純空白）。
- **`_require_int`（L193–210）**：
  - **L195** — 必須是 `int` **且不是 bool**（Python 裡 `True`/`False` 是 `int` 的子類）。
  - **L199–200** — 必須 ≥ `min_value`。
  - **L202–206** — 不可比現在未來超過 300 秒。
  - **L207–210** — 不可比現在舊超過 30 天。
- **`_is_number`（L213–214）** — 是 `int` 或 `float`，但**排除 bool**。這是全檔最關鍵的防呆：
  `isinstance(True, int)` 在 Python 是 `True`，若不排除，`watt=True`／`confidence=False`
  會被當成數字 1／0 溜過去。

---

## Review 發現與我們改了什麼

| 狀態 | 項目 | 動作 |
|---|---|---|
| ✅ 已修 | `_validate_sighting` 與 `_validate_intrusion` 重複了 zone/source/confidence 檢查（~20 行）| 抽出 `_require_zone_source_confidence(payload, kind)` |
| ✅ 已修 | `validators` dict 每次呼叫都重建 | 提到 module 層級的 `VALIDATORS` 常數 |
| ✅ 已修 | 30 天 max-age 與 DynamoDB TTL 的耦合沒說明 | 加註解連結兩者 |
| ⏸️ Parked | `motion/plug/temp/voice` 是舊智慧家庭型別、現在無真實 producer | 到「死代碼」站再決定留/刪（task #12）——這是產品/敘事決定 |

沒有 correctness bug——這層寫得紮實（尤其 bool 防呆那段）。

## 這個檔案可以講的面試點

- **邊界驗證 + 關注點分離**：這層只驗證，不改也不轉。型別轉換（float → Decimal 給 DynamoDB）
  是 handler 的事。這讓本模組維持成純函式、極易單元測試。
- **Dispatch table 取代 if/elif**：O(1)、可擴充（加 `intrusion` 只要一行）、好讀。
- **bool vs int 防呆**（`_is_number`、`_require_int`）：一個很細的 Python correctness 細節，
  展現對真實輸入邊界的注意。
- **把耦合寫明**：max-age ↔ TTL 的註解，記錄了一個跨兩個檔案的 invariant。
