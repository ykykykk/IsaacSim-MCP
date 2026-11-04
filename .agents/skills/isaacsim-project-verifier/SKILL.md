---
name: isaacsim-project-verifier
description: Implement and verify requirements in this IsaacSim-MCP repository using code execution, log inspection, MCP Camera review, runtime read-back, and bounded repair loops. Use for feature work or defect fixes that need evidence from both program behavior and the rendered Isaac Sim scene.
---

# IsaacSim Project Verifier

完成需求後必須以執行結果、log、Camera 畫面與 read-back 證明結果。靜態閱讀或程式碼產生不能取代執行驗證。

## 開始前

1. 先讀取同層的 [`omniverse-windows-workspace`](../omniverse-windows-workspace/SKILL.md)，依任務類型載入必要 reference。
2. 從本 Skill 位置解析 repository root，確認 Git root、branch、HEAD、remote 與 working tree。保留所有既有變更。
3. 把需求拆成可獨立驗收的工作項目，為每項寫出可觀察的完成條件。
4. 若方向無法理解、缺少會改變結果的關鍵資料，或操作超出授權，立即指出。只暫停受影響項目，其餘互不相依的項目繼續完成。
5. 修改前建立可還原且不含秘密資料的備份。Push、release、刪除正式資產或覆寫使用者 Stage 仍需明確授權。

## 主要流程

依序執行：

```text
理解要求與驗收條件
→ 製作或修正需求
→ 執行受影響的程式碼與測試
→ 檢查 command response 與 logs
→ 用 Camera 檢查靜態或動態畫面
→ 用 Stage/runtime read-back 交叉驗證
→ 發現錯誤時修正並重新執行
→ cleanup 與健康檢查
→ 回報關鍵程式碼、畫面、log 與結果
```

任何新增或修改的可執行程式碼都要實際執行。至少跑 focused tests 與 lint；變更碰到 Isaac/Kit/runtime 行為時，再執行 guarded live verifier。不要用 documentation MCP 或 schema-only test 宣稱 live Stage 通過。

## Log 與 Camera 驗證

- 對照同一個 operation window 檢查 MCP response envelope、MCP Server output、Isaac Sim Kit/runtime log，以及適用的 process、port、warning、exception、crash 或 dump 證據。
- 影響可見 Stage、人物、Robot、Physics、Sensor 或動畫的工作必須做 Camera 驗證。優先沿用能看清目標的既有 Camera；不足時建立 verifier-owned scratch Camera，驗證後刪除。不得移動、改寫或刪除使用者原本的 Camera。
- 圖片使用 `capture_camera_output(return_mode="image")` 或等價的 MCP-native `ImageContent` 路徑。動態行為至少比較兩個不同 simulation time/frame 的畫面與 transform read-back。
- 詳細判定與證據要求見 [verification contract](references/verification-contract.md)。

## 三次卡點規則

每個錯誤以「程式碼或 Stage 位置、operation phase、錯誤 signature 或失敗 assertion」識別。

- 同一位置且實質相同的錯誤，在修正後連續出現 3 次，才判定該工作項目 blocked。
- 錯誤移到新的 downstream phase、通過更多驗收條件，或 failure signature 實質改變，代表已有進度；新問題從第 1 次開始計算。
- 第 3 次仍卡在同一位置時，停止該項目的進一步 mutation，保留三次 attempt、程式碼 diff、log、畫面與 read-back，直接回報 blocker。
- Blocked 項目不得阻止互不相依的項目。繼續完成其餘工作，最終分開列出 completed、partial 與 blocked。
- Runtime crash、connection loss、timeout 或 delivery state 不明時，先 read-back。不得盲目重送 write。

## 完成條件

只有同時具備下列證據才能標記完成：

- 需求對應的程式碼或設定已完成。
- 受影響程式碼已實際執行，測試與 lint 結果已記錄。
- 適用的 logs 已檢查，沒有未處理的相關 error。
- 適用的 Camera 畫面合理，且與 Stage/runtime read-back 一致。
- Scratch 資源已清理，timeline、process 與 port 狀態符合預期。
- 最終回報包含關鍵程式碼、實際畫面、檢查結果、未解問題與 Git/backup 狀態。
