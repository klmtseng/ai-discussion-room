# validity-audit — AI 眾議院(部署系統類)

日期:2026-07-08。層級:T1+T2(T3 未要求)。狀態:**第 1 段完成;第 2 段獨立 reviewer 因額度重置(09:10)待補——本審計尚未結案**。

## 受測宣稱與判定

| # | 宣稱 | 判定 | 證據 | PASS 性質 |
|---|---|---|---|---|
| C1 | 41/41 測試通過 | PASS(修復後 48/48) | 主對話親跑 pytest | 可能FAIL,實測 |
| C2 | 匿名化確定性層;主席零模型名 | **FAIL→已修+降級措辭** | 9 案例對抗測試:原版 7/9 洩漏(made by Anthropic、Claude 模型、作為Google的Gemini、GPT-4 級別的我、claude.ai 等中段自報全漏);修復=anonymizer.py 新增 7 組 pattern+tests/test_anonymizer_hardening.py;docstring「Guarantees zero AI model names」撤回,改為「自我身分洩漏清洗;中性第三人稱提及依設計保留(非歸屬訊號)」 | 可能FAIL,實測抓到 |
| C3 | PIN 擋所有 /api/* | PASS | 四端點無 PIN 全 401(實測);server.py:142,195,215 | 可能FAIL,實測 |
| C4 | repo 無憑證可開源 | PASS(附註) | 工作樹+git 全歷史金鑰樣式掃描=0;唯 git author email((author email — redacted, rewritten to noreply pre-publication))在歷史中——與使用者公開 GitHub 身分一致,P3 備註非洩漏 | 可能FAIL,實測 |
| C5 | 素材 CC0/MIT 乾淨 | PASS(附註) | CREDITS.md 逐項;phaser.min.js 含 3.80.1 字串;實際渲染用程式繪圖,Kenney PNG 僅備用未使用;未驗 PNG 與官方 zip 逐位相同(P3:開源前可刪未使用素材或補 checksum) | 部分依賴下載來源可信 |
| C6 | README ToS 警告+Gemini OAuth 說明正確 | PASS | README:7(勿公開部署)、:29(OAuth 停用),與 2026-06-18 官方 deprecation 公告一致(research agent 附官方 URL 查證) | 可能FAIL,對照過外部來源 |

## T2 系統體檢(S1–S7)

- S1 不可重生資產:議事記錄僅存記憶體,重啟即失——設計如此,但使用者若想留總結會消失。P3:建議加「匯出 markdown」。runs/pin.txt 可再生。repo 單機 local-only(開源上 GitHub 後自然解)。
- S2 端到端:真實三委員一輪+隧道+手機截圖都以最終使用方式跑過=PASS;README 安裝步驟未由乾淨環境走過=P3。
- S3 未來檢定:無承諾,n/a。
- S4 已知簡化:in-memory session/Gemini 限速/codex read-only sandbox 已列 README 已知限制=PASS。
- S5 極限配額:adapter 無重試迴圈(唯一 sleep 是 mock);前端輪詢 2s 打本機不打外部 API=PASS。Gemini 免費層 RPM 15,連續快問可能 429——P3:README 可註明。
- S6 孤兒雙入口:scripts/live_smoke.py 唯讀不寫狀態;無持久檔案故無雙寫=PASS。
- S7 機會成本:**該交付了**——UI 打磨(sprite/黑邊)不擋開源;瓶頸在出口。

## 未覆蓋(誠實揭露)

- 獨立 reviewer(冷審+熱審)未跑——額度 09:10 重置後補;**在那之前不得宣稱「過 VA」**。
- prompt injection 面:惡意問題可誘使 codex(read-only sandbox 仍可讀檔)把本機檔案內容帶進回答。單使用者 BYOS 情境=自傷,開源 README 宜加一句安全備註(P2,待 reviewer 複核)。
- 匿名化的殘餘風險:文風/格式本身可識別模型(regex 管不到)——原專案同樣限制,README 已可補充說明(P3)。
