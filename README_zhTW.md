<p align="center">
  <img src="docs/banner.png" alt="Androidbox: Android on your PC. No ads." width="720">
</p>

<p align="center">
  <b>無廣告的 Windows Android 模擬器。</b><br>
  內建 Google Play、遊戲按鍵映射、多開實例，沒有任何廣告與推銷。
</p>

<p align="center">
  <a href="README.md">English</a> | <b>繁體中文</b>
</p>

<p align="center">
  <a href="#features">功能特色</a> ·
  <a href="#getting-started">快速開始</a> ·
  <a href="#how-it-works">運作原理</a> ·
  <a href="#building">自行編譯</a>
</p>

---

Androidbox 直接在您的顯示卡上執行 **Google 官方 Android Emulator**（與 Android Studio 相同的底層引擎），並將畫面呈現在簡潔的視窗中。沒有廣告、不需要建立帳號、沒有捆綁軟體，也不會回傳遙測資料。所有元件皆從 Google 官方伺服器或您自訂的鏡像站下載，所有檔案都集中在單一資料夾內，隨時可完整刪除。

> 除了 Google 官方映像檔與模擬器外不額外安裝任何軟體；因為無法取得 Root，需要檢測 Root 的銀行 App 與遊戲都能正常運作。

<p align="center"><img src="docs/screen.png" alt="Androidbox 執行 Android 16 畫面" width="820"></p>

## 為什麼選擇 Androidbox

| 項目 | Androidbox | 查證方式 |
|---|---|---|
| 廣告與推薦 App | 無 | 所有原始碼皆在本儲存庫公開 |
| 帳號要求 | Androidbox 本身免帳號；Google Play 僅需登入您的 Google 帳號 | 程式內無任何自建帳號系統 |
| 連線伺服器 | 僅 `dl.google.com`（下載映像檔）、GitHub（檢查更新與遊戲相容清單）、Mozilla（手動安裝無廣告瀏覽器時）及您自行新增的鏡像站 | 可直接搜尋原始碼中的網址 |
| Android 引擎 | Google 官方 Android Emulator | 見 [運作原理](#how-it-works) |
| Google Play | 正版 Play 商店（Android 16 / 11） | 內建官方 Google Play 映像檔 |
| 授權條款 | 開源 MIT 授權 | [LICENSE](LICENSE) |

## 快速開始

**系統需求：**
- Windows 10 或 11（64 位元）
- 開啟 **Windows Hypervisor Platform**（若未開啟，Androidbox 會提示並引導至設定頁面）
- 具備最新驅動程式的顯示卡
- 約 4 GB 磁碟空間（存放 Android 系統），每個實例約需 10 GB

**安裝與使用：**
1. 從 Releases 下載或自行編譯 `Androidbox.exe`。
2. 執行後依畫面提示點擊 **Download and install**（僅需執行一次）。
3. 點擊 **啟動 Android（Start Android）** 即可開始使用。

## 功能特色 {#features}

### 介面語言切換（`.pot` / `.po`）
- 支援 **English** 與 **繁體中文** 雙語介面，切換後立即生效、無需重啟運行中的實例。
- 可在 **實例設定 → 進階與擴充 → 介面語言**、**所有實例 → 全域設定 → 介面語言**，或直接點擊左上角 Logo（`Androidbox v<版本>`）旁的 **🌐 地球圖示** 快速切換。
- 語言包採用標準 GNU gettext 格式：
  - 英文範本：[locales/androidbox.pot](locales/androidbox.pot)
  - 繁體中文翻譯：[locales/zh_TW/LC_MESSAGES/androidbox.po](locales/zh_TW/LC_MESSAGES/androidbox.po)

### 貼近桌面使用習慣
- **關閉視窗確認與系統匣常駐**：按下視窗右上角 **X** 時會彈出確認視窗，可選擇 **取消**、**縮小到後台系統匣**（讓遊戲繼續在背景執行）或 **關機並離開**；若開啟「關閉視窗時縮到系統匣」，則直接隱藏至右下角系統匣。
- **版本標示**：側邊欄 Logo 旁與「所有實例」標題列皆會顯示目前版本（例如 `v1.14.1`）。
- **防誤觸設計**：未展開的下拉選單會忽略滑鼠滾輪事件，捲動設定頁面時不會誤觸切換語言、主題或硬體規格。
- **老闆鍵（Boss key）**：全域快捷鍵可一鍵隱藏所有 Androidbox 視窗並靜音（同時靜音媒體與通知音效），再按一次立即恢復。
- **主題切換**：提供 **Classic**（預設）與 **Glitch** 主題。

### 遊戲控制、巨集與多開
- **遊戲按鍵映射**：支援點擊（Tap）、搖桿（WASD / 手把左搖桿）、射擊準星（Aim / Look）、MOBA 技能指向（Skill）、連點（Turbo）、滑動（Swipe）、傾斜體感（Tilt）與巨集綁定。
- **手把與鍵鼠支援**：自動偵測 Xbox / PlayStation / 通用手把，支援即插即用與熱插拔。
- **巨集錄製與步驟編輯**：可錄製點擊、滑動與按鍵操作，並於編輯器調整等待時間與重複次數。
- **多開與獨立設定**：每個實例可各自設定 CPU 核心數、記憶體、解析度、幀率、Proxy 代理伺服器、網路環境模擬與自動化排程。
- **遊戲相容清單**：可瀏覽社群回報的遊戲執行狀況，一鍵套用建議的幀率與按鍵配置。

### 無廣告與隱私選項
- **阻擋廣告**：透過 AdGuard DNS 過濾 App 與遊戲內的廣告聯播網。
- **無廣告瀏覽器**：一鍵安裝 Firefox 與 uBlock Origin，阻擋網頁與 YouTube 廣告。

## 運作原理 {#how-it-works}

Androidbox 透過 Google 官方 Android Emulator 執行原版系統映像檔，並透過模擬器的 gRPC 介面進行高幀率畫面串流與鍵鼠／手把輸入控制，同時支援將 APK / XAPK / APKS 檔案直接拖曳進視窗安裝。

## 自行編譯 {#building}

從原始碼執行：

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pythonw Androidbox.pyw
```

執行測試：

```powershell
.venv\Scripts\python.exe -m unittest tests.test_i18n -v
```

打包 Windows `.exe`（若已安裝 Inno Setup 6 也會一併產生安裝檔）：

```powershell
.\build.ps1
```

若僅需使用 PyInstaller 產生 `dist\Androidbox\Androidbox.exe`（請務必加上 `--add-data` 納入 `locales`）：

```powershell
.venv\Scripts\pyinstaller.exe Androidbox.pyw --name Androidbox --onedir --windowed --noupx `
  --icon assets\androidbox.ico --add-data "assets\androidbox.ico;assets" --add-data "locales;locales" `
  --exclude-module tkinter --collect-all sdl2dll --noconfirm --clean
```

<details>
<summary><b>原始碼結構</b></summary>

- `androidbox/i18n.py`、`locales/`：純 Python `.pot`/`.po` 翻譯載入器與多語系語言包
- `androidbox/installer.py`：從 Google 或鏡像站下載與驗證模擬器、ADB 與系統映像檔
- `androidbox/instances.py`：實例管理、連接埠分配、虛擬硬體、備份與還原
- `androidbox/emulator.py`：模擬器啟動、停止、ADB 與主控台指令
- `androidbox/bridge.py`：gRPC 畫面串流與輸入控制
- `androidbox/keymap.py`、`gamepad.py`：遊戲按鍵映射與手把輸入
- `androidbox/profiles.py`、`settings.py`：設定檔、範本與偏好設定
- `androidbox/ui/`：PySide6 主視窗、分頁、工具列、搜尋面板與對話框

</details>

## 授權條款

[MIT](LICENSE)
