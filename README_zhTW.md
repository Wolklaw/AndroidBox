<p align="center">
  <img src="docs/banner.png" alt="Androidbox: Android on your PC. No ads." width="720">
</p>

<p align="center">
  <b>無廣告的 Windows Android 模擬器。</b><br>
  內建 Google Play、遊戲按鍵映射、多開實例，沒有任何多餘推銷。
</p>

<p align="center">
  <a href="https://github.com/Wolklaw/Androidbox/releases/latest"><img alt="Latest release"
     src="https://img.shields.io/github/v/release/Wolklaw/Androidbox?label=release"></a>
  <a href="https://github.com/Wolklaw/Androidbox/releases"><img alt="Downloads"
     src="https://img.shields.io/github/downloads/Wolklaw/Androidbox/total"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/Wolklaw/Androidbox"></a>
  <a href="https://github.com/Wolklaw/Androidbox/stargazers"><img alt="Stars"
     src="https://img.shields.io/github/stars/Wolklaw/Androidbox"></a>
</p>

<p align="center">
  <a href="https://github.com/Wolklaw/Androidbox/releases/latest"><b>下載 Androidbox 安裝程式</b></a><br>
  Windows 10 或 11 · 免費 · MIT 授權
</p>

<p align="center">
  <a href="README.md">English</a> | <b>繁體中文</b>
</p>

<p align="center">
  <a href="#features">功能特色</a> ·
  <a href="#how-it-works">運作原理</a> ·
  <a href="#using-it">使用方式</a> ·
  <a href="#tips">實用技巧</a> ·
  <a href="#faq">常見問題</a> ·
  <a href="#building">自行編譯</a>
</p>

---

Androidbox 在您的顯示卡上直接執行 **Google 官方 Android Emulator**（與 Android Studio 相同的底層引擎），並將 Android 畫面呈現在單一簡潔視窗中。沒有廣告、不需註冊帳號、沒有捆綁軟體，也不回傳任何遙測資料。所有必要元件皆從 Google 或您自訂的鏡像站下載，所有檔案集中存放在單一資料夾，隨時可完整刪除。

> 除了 Google 官方發行的映像檔之外不額外安裝任何軟體；由於不支援 Root，具備 Root 檢測的銀行 App 與遊戲都能正常運作。

<p align="center"><img src="docs/screen.png" alt="Androidbox 執行 Android 16 並於側邊開啟資訊欄" width="820"></p>

## 為什麼選擇 Androidbox

正在尋找 BlueStacks、LDPlayer、夜神（Nox）或 MuMu 的無廣告替代方案嗎？以下是 Androidbox 的實際運作方式與查證來源：

| | Androidbox | 查證位置 |
|---|---|---|
| 廣告與推薦 App | 無 | 完整原始碼皆在本儲存庫公開 |
| 帳號 | Androidbox 本身免帳號；Google Play 僅需登入您的 Google 帳號 | 程式內無任何自建帳號系統 |
| 連線伺服器 | 僅 `dl.google.com`（下載 Android）、GitHub（檢查更新與讀取遊戲相容清單）、Mozilla（僅在您手動安裝 Firefox 時）及您自行新增的鏡像站 | 可直接搜尋原始碼中的網址 |
| Android 引擎 | Google 官方 Android Emulator（與 Android Studio 相同） | 見 [運作原理](#how-it-works) |
| Google Play | 正版 Play 商店（支援 Android 16 與 Android 11） | [Android 16 與 Google Play](#android-16-with-google-play) |
| 原始碼 | 開源 MIT 授權 | [LICENSE](LICENSE) |
| 費用 | 免費 | |

其他模擬器的隱私政策可自行比較：
[BlueStacks](https://www.bluestacks.com/terms-and-privacy.html)、
[LDPlayer](https://ldplayer.net/other/privacy_policy.html)、
[Nox](https://www.bignox.com/privacy-policy) 與
[MuMu](https://www.mumuplayer.com/privacy-policy.html)。

本專案專注於在電腦上流暢遊玩手機遊戲與執行應用：包含按鍵映射、手把支援、巨集錄製、多開實例，以及支援 OUYA / GameStick 遊戲的實驗性 Android 4.1 映像檔。

## 快速開始

**系統需求：**
- Windows 10 或 11（64 位元）
- 開啟 **Windows Hypervisor Platform**（若未開啟，Androidbox 會主動提示並引導至設定頁面）
- 具備最新驅動程式的顯示卡
- 約 4 GB 磁碟空間（存放 Android 元件），每個實例最多約需 10 GB

**使用步驟：**
1. 從 [Latest Release](https://github.com/Wolklaw/Androidbox/releases/latest) 下載 `Androidbox-Setup-<version>.exe`（或自行編譯 `Androidbox.exe`）。
2. 執行安裝檔。由於尚未進行程式碼簽章，Windows 可能會顯示「未知發行者」警告，請點選 **其他資訊** → **仍要執行**。
3. 依照精靈安裝（可選擇為所有使用者安裝於 `Program Files`，或選擇僅為目前使用者安裝）。若未開啟 Windows Hypervisor Platform，精靈會協助開啟。
4. 開啟 Androidbox 後點選 **Download and install**（僅首次需要）。
5. 按下 **啟動 Android（Start Android）**。

關閉視窗時會詢問要 **縮小到後台系統匣** 或 **關機並離開**（若已開啟「關閉視窗時縮到系統匣」則直接常駐背景）。Androidbox 也支援自動更新（見 [更新](#updates)）。

### 在 Linux 上執行

Androidbox 也支援 Linux，並預定隨 [SparkOS](https://github.com/Wolklaw/sparkos) 一同發行。

**需求：** 64 位元 x86 Linux 桌面環境（KDE Plasma 或 GNOME）、Python 3.10–3.14、已開啟 **KVM**（BIOS 啟用 SVM 或 VT-x，並可存取 `/dev/kvm`），以及與 Windows 相同的磁碟空間。

```bash
git clone https://github.com/Wolklaw/Androidbox.git
cd Androidbox
bash packaging/linux/install.sh --user --deps
androidbox
```

若要安裝給所有使用者（`/usr`），請省略 `--user` 並以 `sudo` 執行；解除安裝可執行 `bash packaging/linux/install.sh --uninstall`（實例資料保留於 `~/.local/share/Androidbox`）。Debian / Ubuntu 請先安裝 `python3-venv libsdl2-2.0-0 libxcb-cursor0 libxkbcommon-x11-0 libegl1 libnss3 libpulse0`。

與 Windows 版的差異：
- **全域快捷鍵與老闆鍵不適用**：Linux 桌面不允許背景程式攔截其他視窗的按鍵；視窗內快捷鍵仍正常運作。
- **無自動自我更新**：SparkOS 由系統更新套件管理版本，Androidbox 僅提示有新版本。
- **省電模式**：一般使用者僅能調降程序優先序，需重啟實例才會恢復。
- **桌面捷徑**為 `.desktop` 檔；登入啟動會寫入 `~/.config/autostart`。
- 透過 SDL 支援遊戲手把（需安裝 `SDL2`）。

## 功能特色 {#features}

### Android 16 與 Google Play {#android-16-with-google-play}

使用 GPU 硬體加速運行於 60、90、120、144 或 240 FPS，並支援 ARM 應用與遊戲。若遇僅提供 32 位元 ARM 的舊款遊戲，可建立 **Android 11** 實例（同時相容 32 位元與 64 位元 ARM）。

每個實例皆可在「設定」中獨立配置硬體：
- **處理器與記憶體**：最高可依電腦實際規格調整，建立時會自動配置合理預設值。
- **顯示解析度**：提供六種常用預設比例，亦可自訂 320–3840 px 與 DPI。
- **儲存空間**：16、32、64 或 128 GB（採動態佔用空間，大型遊戲建議 64 GB 以上）。
- **圖形渲染**：顯示卡加速、自動（Automatic）或軟體渲染（Software，當 GPU 發生相容閃退時切換）。

### 遊戲按鍵映射

每款遊戲各自獨立保存按鍵配置：

| 控制類型 | 功能說明 |
|---|---|
| 點擊 (Tap) | 以鍵盤或手把按鍵對應螢幕上的單點點擊 |
| 搖桿 (Joystick) | 以 WASD（可重新綁定）、方向鍵或左類比搖桿移動 |
| 準星射擊 (Aim) | 射擊模式：按下綁定鍵（F1）鎖定滑鼠並以滑鼠轉動視角，亦支援右搖桿 |
| 視角觀察 (Look) | 自由視角：僅在按住按鍵（Alt）期間以滑鼠轉動視角 |
| 開火與開鏡 | 瞄準模式下直接以滑鼠左／右鍵點擊 |
| 技能施放 (Skill) | MOBA 指向施法：按住按鍵、以滑鼠瞄準、放開施放 |
| 連點 (Turbo) | 按住按鍵即可高速連點該位置 |
| 切換長按 (Hold) | 按一下持續壓住、再按一下放開，適合衝刺與自動奔跑 |
| 滑動 (Swipe) | 單鍵沿著箭頭方向執行拖曳滑動（閃避或切換路線） |
| 傾斜體感 (Tilt) | 以按鍵或左搖桿模擬傾斜方向盤，適合賽車遊戲 |
| 巨集 (Macro) | 單鍵播放錄製好的巨集，再按一次停止 |
| 縮放 (Zoom) | 按住 Ctrl 滾動滑鼠滾輪即可雙指縮放，無需額外設定 |

**預設配置範本（Starter layouts）** 內建射擊、MOBA、賽車、動作平台與跑酷範本，並支援匯出／匯入 JSON 配置檔分享給其他實例或電腦。

<p align="center"><img src="docs/controls.png" alt="在畫面上擺放遊戲按鍵" width="820"></p>

### 遊戲手把支援

隨插即用支援 Xbox、PlayStation、Switch Pro、8BitDo 與多數有線／藍牙手把，可雙手把同樂；未設定遊戲按鍵時可直接操作 Android（A 確認、B 返回、Start 主畫面）。

### 巨集腳本與智慧步驟

錄製點擊、滑動與按鍵操作後，可以 0.5x、1x、2x 或 4x 速度重播，並可設定重複次數、間隔等待時間、步驟微調與全域快捷鍵（**Works in any program**）。

**智慧步驟（Smart steps）** 讓巨集能依據畫面內容自動判斷：
- **等待指定區域符合畫面**：框選按鈕或標題，出現後才繼續執行（可用「Check now」即時測試）。
- **等待畫面停止變化**：適合讀取載入畫面。
- **條件判斷（If / End if）**：僅在指定區域符合時才執行該段步驟。
- **條件迴圈（Repeat）**：重複執行直到指定區域出現或達上限次數。
- **全域尋圖點擊**：在整個畫面中搜尋按鈕圖示並點擊中央（適合位置會變動的「領取／跳過」按鈕）。

### 設定檔與跨電腦同步

設定檔會集中保存您的遊戲按鍵配置、巨集、實例範本與偏好設定，可隨時於右上角選單切換：
- 將實例硬體配置儲存為 **範本（Preset）**。
- 匯出／匯入單一設定檔。
- 透過 OneDrive、Dropbox、Google Drive 或 Syncthing 同步資料夾在多台電腦間共享設定檔（無須登入帳號，Androidbox 不會自行上傳任何資料）。

### 快速搜尋、側邊資訊欄與外觀主題

- **全域搜尋（`Ctrl+K`）**：一鍵搜尋頁面、實例、動作、設定、快照與巨集。
- **側邊資訊欄（`Ctrl+I`）**：在遊戲畫面旁即時顯示快照、自動掛機、排程、網路模擬與巨集。
- **側邊欄實例卡片**：即時顯示縮圖與 CPU／記憶體用量，懸停即可直接啟停。
- **精簡工具列**：常用按鈕位於工具列，音量調整、安裝 APK、檔案互傳、虛擬定位、搖晃、省電、同步與靜音集中於 **...** 選單。
- **設定搜尋**：在設定頁頂部輸入關鍵字或點擊分類快速跳轉。
- **Glitch 主題**：可於設定切換 **Classic**（預設）與 **Glitch** 主題（深靛藍配薄荷綠與故障掃描線效果），即時套用免重啟。

### 多開管理

在 **所有實例（All instances）** 頁面可建立、複製、單檔備份／還原、一鍵全部啟動／停止、彈出獨立視窗、並排排列視窗，以及同步操作所有運行中的實例。

### 應用程式與遊戲

在 **應用程式（Apps）** 頁面可查看已安裝清單、為個別遊戲設定專屬幀率、解除安裝或建立桌面捷徑。捷徑與第三方啟動器（如 LaunchBox）皆支援命令列參數：
`Androidbox.exe --instance <名稱或id> --launch <套件名稱> --fullscreen`、`--background`、`--stop <名稱或id>`、`--start-all`、`--stop-all`。

### 遊戲相容清單

側邊欄的 **遊戲相容清單（Game list）** 彙整玩家回報的遊戲運行相容性與建議設定（每日最多從 GitHub 同步一次，亦可於全域設定關閉）。若想貢獻測試結果，可在應用程式的 **⋯** 選單點選 **分享至遊戲相容清單…** 或提交 [遊戲回報 Issue](https://github.com/Wolklaw/Androidbox/issues/new?template=game_report.yml)。

### 狀態快照與自動化

- **狀態快照（Saved states）**：完整保存目前系統狀態、應用程式與畫面，幾秒內即可快速載入還原。
- **自動化排程（Automation）**：支援閃退自動重開指定遊戲（掛機必備）與每日定時開關機。

### 網路模擬與 Proxy 代理

- **網路環境模擬**：即時切換 4G、3G、EDGE 或 GPRS 網速與延遲測試。
- **網路代理（Proxy）**：支援 HTTP 與 SOCKS5（含帳號密碼驗證，內建本機中繼器），並提供 **測試** 與診斷工具確認連線。

### 更新機制 {#updates}

Androidbox 啟動與運行期間會定期檢查 GitHub 是否有新版本，並在背景下載與驗證 SHA-256 校驗碼，確認無誤後才詢問是否重啟更新。

### 不干擾日常使用

- **系統匣與關閉確認**：按下視窗右上角 **X** 會彈出確認視窗，可選擇 **縮小到後台系統匣**（讓遊戲繼續在背景執行）或 **關機並離開**；若開啟「關閉視窗時縮到系統匣」，則直接縮小常駐於右下角系統匣。
- **介面語言切換（`.pot` / `.po`）**：可在實例設定、全域設定或點擊左上角 Logo（`v<版本>`）旁的 **🌐 地球圖示** 在 **English** 與 **繁體中文** 間即時切換；翻譯檔位於 `locales/androidbox.pot` 與 `locales/zh_TW/LC_MESSAGES/androidbox.po`。未展開的下拉選單會忽略滑鼠滾輪事件，避免捲動頁面時誤觸切換。
- **隨 Windows 開機啟動**：開機自動進入系統匣並啟動指定實例。
- **老闆鍵（Boss key）**：全域快捷鍵一鍵隱藏所有視窗並靜音（同步靜音媒體與通知音效），再按一次恢復。
- **單獨靜音與視窗置頂**：可針對單一實例靜音或將視窗固定在最上層。

<p align="center"><img src="docs/instances.png" alt="實例管理頁面" width="820"></p>

### 下載鏡像站

若 Google 伺服器連線較慢或受阻，可在首次設定或 **所有實例 → 本機電腦設定 → 下載鏡像站** 新增替代網址（每行一個，例如 `https://mirrors.cloud.tencent.com/AndroidSDK/`），所有下載仍會驗證 SHA-1 校驗碼。

### 兩種無廣告防護

- **阻擋廣告**：透過 AdGuard DNS 過濾 App 與遊戲內的廣告聯播網。
- **無廣告瀏覽器**：一鍵安裝 Mozilla Firefox 與 uBlock Origin，阻擋網頁與 YouTube 廣告。

### 讓 Claude Code 協助測試 App

預設關閉。於全域設定開啟 **允許 Claude Code 控制 Android** 後，會將輔助程式寫入 `%LOCALAPPDATA%\Androidbox\claude` 並註冊為 Claude Code 的 MCP Server（關閉開關即移除），支援截圖、讀取 UI 樹、點擊、滑動、輸入與安裝測試。

<p align="center"><img src="docs/settings.png" alt="實例設定頁面" width="820"></p>

## 運作原理 {#how-it-works}

<p align="center">
  <img src="docs/how-it-works.png" alt="Androidbox 透過共享記憶體與 gRPC 連接 Android Emulator" width="520">
</p>

1. **首次執行**：自動下載並校驗 Google Android Emulator、ADB 與 Android 16 系統映像檔（約 1.9 GB）至 `%LOCALAPPDATA%\Androidbox`（Android 11 約 1.4 GB 僅於建立該版本實例時下載）。
2. **啟動 Android**：以無獨立視窗模式呼叫模擬器並啟用 GPU 加速，幾秒內從快照恢復。
3. **畫面與輸入**：透過 gRPC 與共享記憶體直接取得畫面幀，並將鍵鼠與手把事件轉為多點觸控與按鍵事件。
4. **遊戲按鍵**：將鍵盤、滑鼠移動與手把類比輸入轉換為指定螢幕座標的觸控操作。
5. **關機保存**：停止時自動儲存快照，下次啟動無縫接續。

## 使用方式 {#using-it}

- **滑鼠**：左鍵點擊、拖曳滑動、滾輪捲動、右鍵返回、中鍵主畫面。
- **鍵盤**：輸入文字直接傳送至 Android，`Esc` 為返回鍵。
- **檔案**：直接將 APK / XAPK / APKS 或一般檔案拖曳至視窗即可安裝或傳輸。

| 快捷鍵 | 功能 |
|---|---|
| F11 | 全螢幕 |
| Ctrl+Shift+S | 螢幕截圖（存於 `Pictures\Androidbox`） |
| Ctrl+Shift+R | 螢幕錄影（存於 `Videos\Androidbox`） |
| Ctrl+Shift+K | 開啟／關閉遊戲按鍵 |
| Ctrl+Shift+E | 編輯遊戲按鍵 |
| Ctrl+Shift+M | 錄製巨集 |
| Ctrl+Shift+O | 旋轉螢幕 |
| Ctrl+Shift+W | 在獨立視窗中開啟 |
| Ctrl+滾輪 | 雙指縮放 |

## 實用技巧 {#tips}

- **使用 Google Play 需登入 Google 帳號**；若不想登入，可直接拖曳 `.apk` 安裝並使用無廣告瀏覽器看 YouTube。
- **遊戲需要更高效能？** 可在設定調高處理器核心數與記憶體，或切換為平板橫向顯示；空間不足請調大 **儲存空間**（變更儲存容量會清除該實例資料）。
- **啟動時閃退？** 在設定將「圖形渲染」改為「自動（Automatic）」或「軟體渲染（Software）」。
- **需要背景掛機？** 開啟該實例的「省電模式（Eco mode）」。
- **僅支援 32 位元 ARM 的舊遊戲？** 請建立 **Android 11** 實例安裝。
- **高更新率螢幕？** 可於設定將幀率調至 144 或 240 FPS（受遊戲本身鎖幀限制者除外）。

## 常見問題 {#faq}

<details>
<summary><b>真的完全無廣告嗎？</b></summary>

Androidbox 本身永久無廣告。Android 內部可開啟「阻擋廣告」過濾廣告聯播網，並使用「無廣告瀏覽器」阻擋網頁與 YouTube 廣告（部分由 App 自家伺服器直接下發的廣告則無法以 DNS 過濾）。

</details>

<details>
<summary><b>支援 Root 嗎？</b></summary>

不支援。Google Play 官方映像檔無法 Root，優點是銀行 App 與反作弊遊戲不會因偵測到 Root 而閃退。

</details>

<details>
<summary><b>需要建立帳號嗎？</b></summary>

不需要。設定檔僅保存在您的本機電腦，除非您自行設定同步資料夾，否則不會離開您的電腦。

</details>

<details>
<summary><b>資料存放在哪裡？如何移除？</b></summary>

所有資料位於 `%LOCALAPPDATA%\Androidbox`（主程式位於 `Program Files`），可在「所有實例 → 資料存放位置」遷移至其他磁碟機。從 Windows 設定解除安裝時會詢問是否一併刪除資料夾。

</details>

<details>
<summary><b>Google 連線慢或被封鎖怎麼辦？</b></summary>

可在首次啟動畫面或「所有實例 → 下載鏡像站」加入鏡像網址（如 `https://mirrors.cloud.tencent.com/AndroidSDK/`），所有下載仍會檢查 SHA-1 校驗碼。

</details>

<details>
<summary><b>《Pokémon GO》或《Clash of Clans》可以玩嗎？</b></summary>

無法遊玩，這些遊戲會主動偵測 Play Integrity 或模擬器環境並直接關閉，Androidbox 不會刻意偽裝或繞過遊戲的反作弊保護。

</details>

<details>
<summary><b>為什麼選擇 Android 16 而不是最新測試版？</b></summary>

Google 的正式遊戲相容性在 Android 16 最為穩定，其 ARM 轉譯器已修復 Android 15 上部分 Unity 遊戲閃退的問題；Android 11 則保留給僅有 32 位元 ARM 的舊遊戲。

</details>

## 自行編譯 {#building}

```powershell
.\build.ps1
```

若要從原始碼直接執行：

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pythonw Androidbox.pyw
```

執行單元測試（含 `.pot`/`.po` 多語系測試）：

```powershell
.venv\Scripts\python.exe -m unittest tests.test_i18n -v
```

<details>
<summary><b>原始碼結構</b></summary>

- `androidbox/installer.py`：下載與驗證模擬器、ADB 與系統映像檔
- `androidbox/instances.py`：實例、連接埠、虛擬硬體、備份與還原
- `androidbox/emulator.py`：啟動與停止模擬器、ADB 與主控台指令
- `androidbox/bridge.py`：gRPC 畫面串流、觸控、按鍵與感測器
- `androidbox/keymap.py`、`gamepad.py`：遊戲按鍵映射與手把輸入
- `androidbox/profiles.py`、`settings.py`、`i18n.py`：設定檔、範本、偏好設定與 `.pot`/`.po` 介面翻譯（`locales/`）
- `androidbox/macros.py`、`browser.py`：巨集錄製編輯與無廣告瀏覽器
- `androidbox/system.py`、`relocate.py`、`hotkeys.py`：系統資訊、開機啟動、資料遷移與全域快捷鍵
- `androidbox/diagnostics.py`：診斷日誌打包
- `androidbox/ui/`：PySide6 主視窗、分頁、搜尋面板、資訊欄與對話框
- `androidbox/proto/`：模擬器 gRPC 定義產生的綁定程式碼
- `build.ps1`、`setup.iss`、`installer/`：PyInstaller 打包與 Windows 安裝程式腳本

</details>

## 致謝

- **Android Emulator**、系統映像檔與 `emulator_controller.proto` 由 Android Open Source Project 與 Google 提供（Apache License 2.0 / Android SDK License）。
- **Firefox**（Mozilla）、**uBlock Origin**（Raymond Hill 等貢獻者）、**AdGuard DNS**（AdGuard）。
- 使用 **Qt for Python (PySide6)**、**gRPC** 與 **SDL (PySDL2)** 開發。

## 程式碼簽章政策

目前安裝程式尚未進行程式碼簽章，已向 SignPath.io 申請免費開源簽章憑證。

## 授權條款

Androidbox 採用 [MIT License](LICENSE) 釋出。
