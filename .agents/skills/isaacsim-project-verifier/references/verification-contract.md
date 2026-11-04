# Verification Contract

本 reference 定義 Camera、動態行為、log、修復迴圈與最終回報的最低證據。只在任務需要執行或 live 驗證時載入。

## 需求與工作項目

每個工作項目先記錄：

- 預期結果與不得改變的既有行為。
- 依賴項、runtime prerequisite 與操作授權。
- 可執行 test、live verifier、read-back 與 cleanup 方法。
- 是否影響其他工作項目。互不相依的項目必須能單獨完成與回報。

遇到無法理解的要求時，先指出具體歧義與受影響範圍。缺少資訊只暫停依賴該資訊的工作項目。

## 程式碼與 log

修改可執行程式碼後至少檢查：

1. Focused test 或最小 reproduction。
2. Repository lint、type/schema 或 generated inventory gate，依變更類型選擇。
3. 適用的完整離線 test suite。
4. Isaac/Kit 行為變更的 guarded live verifier。

在同一驗證時間窗內保留：

- 執行 command、exit code、pass/fail count 與 elapsed time。
- MCP response 的 `status`、`code`、`message`、`command_id`、`warnings`、`timing`、`artifacts` 與 `readback`。
- MCP Server 與 Isaac Sim Kit/runtime 的相關 warning、error、exception、traceback、crash signature 與 dump。
- Runtime process、TCP `8766` 與使用中的 HTTP MCP port 在操作後是否仍健康。

只報告與該 operation 時間窗或程式碼路徑相關的 log。無法證明關聯的舊 warning 要標為背景資訊，不能冒充本次 failure。

## Camera 畫面合理性

### 靜態畫面

檢查：

- 目標物件、人物、Robot 與環境是否存在且可辨識。
- 位置、方向、比例、材質、顏色、光照與陰影是否符合需求。
- 是否有穿模、碰撞滲透、浮空、陷入地面、錯誤堆疊、意外重疊或超出場景。
- Camera 是否對準目標，frame 是否為最新、非空、非全黑且解析度正確。

### 人物模型與動態行為

至少擷取兩個不同 simulation time 或 frame 的畫面，並讀回人物 root transform、target、behavior state 與可用的 animation/navigation 狀態。檢查：

- Mesh、skeleton、skin、材質、比例、姿勢與朝向是否合理。
- 四肢是否扭曲、缺失、拉伸、穿過身體或穿過環境。
- Walk/MoveTo 狀態下是否有可量測的 world-space 位移，方向是否朝向 target。
- 動畫播放但 root 長時間停在原地，且需求沒有指定 in-place locomotion，判定為失敗。
- Root 位移但動畫保持 idle、腳底明顯滑動、瞬移、漂移或速度不合理，判定為失敗。
- LookAt、Idle、Stop 等狀態是否在畫面與 read-back 同時成立。

單張圖片只能證明該 frame 的外觀。位移、速度、動畫進度與 lifecycle 必須以多 frame 加 read-back 驗證。

### Camera 所有權

- 優先使用現有 Camera，但不得修改其 transform、resolution 或 lifecycle。
- 需要新視角時，在唯一 verifier-owned namespace 建立 scratch Camera。
- 使用 MCP-native `ImageContent` 回傳畫面。若 client 無法顯示，保留 managed artifact 與 hash 作為 partial evidence。
- 驗證後刪除 scratch Camera，確認 prim 與 render product 沒有重現。

## Error repair ledger

每次修復記錄：

| 欄位 | 內容 |
|---|---|
| Work item | 受影響工作項目 |
| Location | file/function/tool/prim/runtime phase |
| Signature | error code、exception 或 failed assertion |
| Attempt | 同一位置第 1、2 或 3 次 |
| Change | 本次最小修正 |
| Result | 通過、前進到新 phase，或相同錯誤仍存在 |
| Evidence | test、log、image、read-back |

同一位置第 3 次仍出現相同錯誤後：

1. 停止該工作項目的 mutation。
2. 保留現場、避免無界 retry 或危險 workaround。
3. 回報 root cause 已知程度、三次修正、目前 blocker 與安全下一步。
4. 繼續所有不依賴該 blocker 的工作項目。

## 最終回報格式

依實際內容提供：

1. `Completed / Partial / Blocked` 工作項目與原因。
2. 關鍵程式碼片段，以及可點擊的完整檔案與行號。
3. 實際 Camera 圖片或 artifact link，附上畫面判定。
4. 執行過的 tests、lint、live verifier、exit code 與結果。
5. Log 檢查範圍、相關 warning/error，或確認沒有相關 error。
6. Stage/runtime read-back、cleanup、process 與 port 健康狀態。
7. 三次卡點 ledger 與仍需處理的 blocker。
8. Backup、Git status、commit 與 push 狀態。不得把未推送內容寫成已發布。
