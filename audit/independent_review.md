# 獨立 reviewer 報告(VA 第 2 段)— 2026-07-08

兩輪皆 opus、fresh context、未參與建造。冷審不給提示清單;熱審給前兩輪發現+要求攻擊清單本身。
(盲區備註:無其他模型家族可用,兩輪同為 Claude 家族——與建造者共用盲點的風險已知,靠「冷審零提示+熱審攻清單」部分緩解。)

## 冷審(不給提示)

- **P2-1** filter_self_id 漏新句型:"This response comes from Gemini." / "My name is Claude." / "(Powered by GPT-4)" / "Claude thinks…" 全穿透(重現:python3 -c import anonymizer 直測)。README 稱該層為 primary defence=過度宣稱。
- **P3-1** /api/config 閒置桌序=config 順序,與該輪洗牌可能不一致(cosmetic,server.py 自我記錄)。
- **P3-2** CREDITS.md 在 static/assets 非 root;phaser.min.js 無內嵌 MIT 標頭。
- 六宣稱:測試/PIN/無祕密/README=可信;匿名化=部分可信(結構面成立、blocklist 面過強);素材=部分可信(位置)。
- 結論:可安全開源;唯一實質缺口=匿名化宣稱過強。

**修復(commit 73408fc)**:build_chair_prompt 咽喉點加 redact_model_names() 硬遮蔽(委員回答+追問問答;共用主議題豁免);README 三層誠實重寫;冷審 6 個洩漏句型釘成測試;CREDITS 指標入 README。

## 熱審(攻修復本身+清單本身)

- **P1-1** 裸「Google」不在 _BRAND_RE("My developer is Google." 整條管線穿透)——Gemini 自報供應商最自然說法,直接歸屬洩漏。
- **P2-1** 非大三廠品牌零覆蓋:config 可自訂席位(如本地 Mistral),其品牌不會被遮。
- **P3-1** PIN 非常數時間比對且無節流;**P3-2** sessions 無界成長;**P3-3** codex prompt 無 `--` 分隔(現況不可達,深度防禦)。
- 已查證無問題:chair 無旁路文字路徑;同席併發追問無丟 turn;homoglyph 繞法需模型自己產出特殊字形,不現實不列;PIN 401 四端點+路徑穿越皆擋。
- 立場:**維持可開源,P1-1 為開源前必修**。
- 清單盲區:①只審模型自報、漏「廠商名=常用詞」雙義詞;②把 adapter 集合當常數,沒對可擴充點建模;③只驗文字內容、不驗形態/通道(節流、無界成長)。

**修復(本 commit)**:_BRAND_RE 加裸 Google/Meta/xAI/Grok/Mistral/Llama/DeepSeek/Qwen;redact_model_names 支援 extra_brands=config 動態品牌(parliament 傳入 model_display+adapter);hmac.compare_digest;sessions 上限 50 淘汰最舊已完成;codex 加 `--`(--help 驗證+live smoke 實跑通過);新增 7 測試(共 78)。

## 重現閘門記錄

冷審 6 句型+熱審裸 Google 3 句型:全部先以 python3 直測重現後才計入;修復後全部進 tests/ 永久釘死。
