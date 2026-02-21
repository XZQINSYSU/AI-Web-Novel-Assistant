# ai_worker.py
from PyQt6.QtCore import QThread, pyqtSignal
from openai import OpenAI
import json

class AIWorker(QThread):
    reasoning_signal = pyqtSignal(str)
    content_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, api_key, base_url, model, temperature, max_tokens, system_prompt, user_prompt):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            response = client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": self.user_prompt}
                ],
                stream=True
            )

            for chunk in response:
                if self._is_cancelled:
                    break
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    self.reasoning_signal.emit(reasoning)
                content = getattr(delta, "content", None)
                if content:
                    self.content_signal.emit(content)

            self.finished_signal.emit()
        except Exception as e:
            self.error_signal.emit(str(e))

class AutoPilotWorker(QThread):
    # 状态与UI更新信号
    status_signal = pyqtSignal(str)  # 通知UI当前在干嘛
    log_signal = pyqtSignal(str)  # 输出思考日志
    content_signal = pyqtSignal(str)  # 实时正文输出

    reasoning_signal = pyqtSignal(str)
    start_chapter_signal = pyqtSignal(int, int)  # 传递 v_idx, c_idx

    # 结构操作信号 (让主线程去操作数据，避免跨线程读写冲突)
    add_volume_signal = pyqtSignal(str, str)  # vol_name, synopsis
    add_chapter_signal = pyqtSignal(int, str, str)  # v_idx, chap_name, ai_synopsis
    save_content_signal = pyqtSignal(int, int, str, str)  # v_idx, c_idx, content, ai_summary

    # 【新增】专门用于更新“已有章节”和“已有卷宗”的梗概
    update_chapter_signal = pyqtSignal(int, int, str)
    update_volume_signal = pyqtSignal(int, str)  # <--- 新增这行：传递 v_idx, synopsis

    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, api_key, base_url, model, temperature, project_meta):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.project = project_meta  # 【修改处】保存整个 project 对象
        self.meta = project_meta.meta  # 传入当前项目的快照
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True
        # 【新增】强制关闭 OpenAI 客户端，打断可能正在阻塞的网络请求
        if hasattr(self, 'client'):
            try:
                self.client.close()
            except Exception:
                pass

    def run(self):
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

            # 阶段 1：规划后续所有卷宗
            self.status_signal.emit("🔄 阶段 1/3: 正在统筹全局，规划后续卷宗...")
            self._plan_volumes()
            if self._is_cancelled: return

            # 阶段 2：遍历卷宗，规划每一卷的详细章节
            self.status_signal.emit("🔄 阶段 2/3: 正在为每一卷规划章节细纲...")
            self._plan_chapters()
            if self._is_cancelled: return

            # 阶段 3：逐章生成正文
            self.status_signal.emit("🔄 阶段 3/3: 开启全自动挂机码字模式！")
            self._generate_all_contents()

            if not self._is_cancelled:
                self.status_signal.emit("✅ 全书挂机生成完毕！")
            self.finished_signal.emit()

        except Exception as e:
            self.error_signal.emit(str(e))

    def _call_llm_for_json(self, system_prompt, user_prompt):
        """请求 LLM 并强制返回 JSON 格式"""
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            response_format={"type": "json_object"},  # 强制JSON输出
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        return json.loads(response.choices[0].message.content)

    def _plan_volumes(self):
        existing_vols_info = []
        has_blank_volumes = False

        # 遍历排查有没有“空卷”
        for v in self.meta["volumes"]:
            syn = v.get("synopsis", "")
            if len(syn.strip()) < 10:
                has_blank_volumes = True
            existing_vols_info.append({
                "name": v["name"],
                "synopsis": syn
            })

        current_vol_count = len(self.meta["volumes"])

        # 【修改处】双重判定：数量达标 且 没有空卷，才跳过
        if current_vol_count >= 5 and not has_blank_volumes:
            self.log_signal.emit("⏭️ 当前卷数已达标（>=5卷）且无空白卷梗概，跳过卷宗规划。")
            return

        global_synopsis = self.meta.get("global_synopsis", "")

        sys_prompt = "你是一位网文写手。必须返回严格的JSON对象。"
        user_prompt = f"""
【全局大纲】
{global_synopsis}

【目前已有的卷宗信息】
{json.dumps(existing_vols_info, ensure_ascii=False)}

任务指令：
1. 遍历【目前已有的卷宗信息】。如果某卷的 synopsis 为空或非常简短，请严格依据【全局大纲】和上下文，为其扩写为详细的剧情走向梗概（绝不能改变原有的卷名！）。如果该卷的 synopsis 已经有具体内容，请原样保留，不要做任何删改。
2. 判断故事是否完结。如果未完结，请在 new_volumes 中继续规划后续所需的新卷宗（卷名与详细梗概）。
3. 扩写的内容不可过于俗套

返回格式（严格JSON）：
{{
    "updated_existing_volumes": [
        {{"name": "已有卷名", "synopsis": "扩写后或原样保留的详细梗概"}}
    ],
    "new_volumes": [
        {{"name": "新卷名", "synopsis": "新规划的详细梗概"}}
    ]
}}
如果已完结，"new_volumes" 传空列表。
"""
        result = self._call_llm_for_json(sys_prompt, user_prompt)

        # 1. 先更新那些原本梗概为空的已有卷
        for updated_vol in result.get("updated_existing_volumes", []):
            if self._is_cancelled: break
            for v_idx, v in enumerate(self.meta["volumes"]):
                if v["name"] == updated_vol["name"]:
                    # 只有当原先确实偏短，或者更新内容更长时才覆盖，保护用户自己写的文本
                    if len(v.get("synopsis", "")) < len(updated_vol["synopsis"]):
                        self.update_volume_signal.emit(v_idx, updated_vol["synopsis"])
                        v["synopsis"] = updated_vol["synopsis"]
                        self.log_signal.emit(f"📝 补充空白卷宗梗概：{v['name']}")
                    break

        # 2. 再处理全新增加的卷
        for vol in result.get("new_volumes", []):
            if self._is_cancelled: break

            # 防重机制
            existing_names = [v["name"] for v in self.meta["volumes"]]
            if vol["name"] in existing_names:
                continue

            self.add_volume_signal.emit(vol["name"], vol["synopsis"])
            self.log_signal.emit(f"📚 自动创建新卷：{vol['name']}")

    def _plan_chapters(self):
        for v_idx, vol in enumerate(self.meta["volumes"]):
            if self._is_cancelled: break

            existing_chaps = vol.get("chapters", [])
            current_chap_count = len(existing_chaps)
            has_blank_chapters = False
            existing_chaps_info = []

            for c in existing_chaps:
                ai_syn = c.get("ai_synopsis", "")
                user_syn = c.get("synopsis", "")
                if len(ai_syn.strip()) < 10 and len(user_syn.strip()) < 10:
                    has_blank_chapters = True

                existing_chaps_info.append({
                    "name": c["name"],
                    "user_synopsis": user_syn,
                    "ai_synopsis": ai_syn
                })

            if current_chap_count >= 4 and not has_blank_chapters:
                self.log_signal.emit(f"⏭️ {vol['name']} 章节数已达标(>=4)且无空白梗概，跳过细纲规划。")
                continue

            # 【新增逻辑】：在每一次规划当前卷的章节前，重新获取一遍整本书的最新全局上下文
            # 这样不仅能看到以前的卷，还能实时看到刚刚（在本轮循环中）被 AI 扩写或新建出来的章节！
            all_context_str = "【全书全局卷章概览（包含最新剧情动态）】\n"
            for temp_v in self.meta["volumes"]:
                all_context_str += f"▶ {temp_v['name']} (本卷梗概: {temp_v.get('synopsis', '无')})\n"
                for temp_c in temp_v.get("chapters", []):
                    # 优先读取 AI 之前生成的详细梗概，如果没有则降级读取用户的细纲
                    temp_ai_syn = temp_c.get("ai_synopsis", "")
                    temp_user_syn = temp_c.get("synopsis", "")
                    display_syn = temp_ai_syn if temp_ai_syn.strip() else (
                        temp_user_syn if temp_user_syn.strip() else "暂无梗概")
                    all_context_str += f"  - {temp_c['name']}: {display_syn}\n"
                all_context_str += "\n"

            sys_prompt = "你是一个专业且注重伏笔与逻辑连贯的顶级网文写手和主编。必须返回严格的JSON对象。"
            user_prompt = f"""
{all_context_str}

【当前任务目标】：{vol['name']}
【本卷核心梗概】：{vol.get('synopsis', '无')}
【本卷已有章节信息】：{json.dumps(existing_chaps_info, ensure_ascii=False)}

任务指令：
1. 请充分阅读上方的【全书全局卷章概览】，在补齐章节名和扩写梗概时，必须结合所有卷宗梗概和已有章节的剧情走向，确保前后呼应、不吃书、情节不割裂。
2. 遍历【本卷已有章节信息】。如果某章的 ai_synopsis 为空或较短，请严格依据用户的 user_synopsis（绝不能吞掉或改变用户原意！）并结合前后文将其扩写为包含具体情节和细节的详细梗概。
3. 判断本卷故事是否完结。如果未完结，请在 new_chapters 中结合全局背景继续规划后续的全新章节名与详细梗概，直至本卷剧情完美闭环。

返回格式（严格JSON）：
{{
    "updated_existing_chapters": [
        {{"name": "已有章节名", "ai_synopsis": "扩写后的详细梗概"}}
    ],
    "new_chapters": [
        {{"name": "新章节名", "ai_synopsis": "新规划的详细梗概"}}
    ]
}}
"""
            result = self._call_llm_for_json(sys_prompt, user_prompt)

            for updated_chap in result.get("updated_existing_chapters", []):
                if self._is_cancelled: break
                for c_idx, c in enumerate(vol["chapters"]):
                    if c["name"] == updated_chap["name"]:
                        # 只有当原先确实偏短，或者更新内容更长时才更新，保护心血
                        if len(c.get("ai_synopsis", "")) < len(updated_chap["ai_synopsis"]):
                            self.update_chapter_signal.emit(v_idx, c_idx, updated_chap["ai_synopsis"])
                            c["ai_synopsis"] = updated_chap["ai_synopsis"]
                        self.log_signal.emit(f"📝 补充空白章节细纲：{vol['name']} - {c['name']}")
                        break

            for chap in result.get("new_chapters", []):
                if self._is_cancelled: break

                # 防重机制
                existing_names = [c["name"] for c in vol["chapters"]]
                if chap["name"] in existing_names:
                    self.log_signal.emit(f"⚠️ 拦截到 AI 重复生成的章节：{chap['name']}，已自动跳过。")
                    continue

                self.add_chapter_signal.emit(v_idx, chap["name"], chap["ai_synopsis"])
                # 【修复说明】：删除了 vol["chapters"].append 代码，因为主线程已经通过信号处理了
                self.log_signal.emit(f"📄 自动规划补齐新章节：{vol['name']} - {chap['name']}")

    def _generate_all_contents(self):
        # 遍历所有卷和章，寻找没有内容（或者还没写）的章节开始写
        for v_idx, vol in enumerate(self.meta["volumes"]):
            for c_idx, chap in enumerate(vol["chapters"]):
                if self._is_cancelled: return

                # 这里假设如果章节还没有内容，我们就自动写它
                # 为了简便，我们每次生成都会把正文传回主线程
                existing_content = self.project.read_chapter_content(vol["name"], chap["name"])
                if len(existing_content.strip()) > 100:
                    self.status_signal.emit(f"⏭️ 跳过已写章节：{vol['name']} - {chap['name']}")
                    continue  # 已经有内容了，直接跳过生成，保护用户的心血！

                self.status_signal.emit(f"✍️ 正在挂机生成：{vol['name']} - {chap['name']}")
                self.log_signal.emit(f"开始撰写：{chap['name']}...")

                self.start_chapter_signal.emit(v_idx, c_idx)

                # 构建 prompt (使用与你之前类似的方法，但在 Worker 内组装)
                prev_v_idx, prev_c_idx = -1, -1

                history_str = ""  # 组装过往 ai_synopsis
                for i in range(v_idx + 1):
                    v = self.meta["volumes"][i]
                    limit = c_idx if i == v_idx else len(v["chapters"])
                    for j in range(limit):
                        history_str += f" - {v['chapters'][j]['name']}: {v['chapters'][j].get('ai_synopsis', '')}\n"

                        # 【新增】寻找并读取上一章的正文内容
                        prev_v_idx, prev_c_idx = -1, -1
                        if c_idx > 0:
                            prev_v_idx, prev_c_idx = v_idx, c_idx - 1
                        elif v_idx > 0:
                            # 去上一卷找最后一章
                            for i in range(v_idx - 1, -1, -1):
                                if len(self.meta["volumes"][i]["chapters"]) > 0:
                                    prev_v_idx = i
                                    prev_c_idx = len(self.meta["volumes"][i]["chapters"]) - 1
                                    break

                prev_chapter_content = ""
                if prev_v_idx != -1 and prev_c_idx != -1:
                    pv_name = self.meta["volumes"][prev_v_idx]["name"]
                    pc_name = self.meta["volumes"][prev_v_idx]["chapters"][prev_c_idx]["name"]
                    # 直接调用 project 的读取方法
                    prev_chapter_content = self.project.read_chapter_content(pv_name, pc_name)
                    # 截断太长的上一章内容 (保留后1500字左右即可，节省Token并保证承接)
                    # 【修复1】缩短上一章上下文，防止注意力劫持 (改为1500字)
                    if len(prev_chapter_content) > 1500:
                        prev_chapter_content = "...(前文省略)...\n" + prev_chapter_content[-1500:]

                    # 【修复2】提取缺失的人物设定
                char_texts = [f"【{c['name']}】 性别:{c['gender']} 性格:{c['personality']} 经历:{c['experience']}" for c
                              in self.meta.get("characters", [])]
                char_setting = "\n".join(char_texts) if char_texts else "未提供明确人物。"

                sys_prompt = f"""你是一位经验丰富的网文大神作家。
                    【全局大纲】：{self.meta.get('global_synopsis', '')}
                    【核心人物设定】：\n{char_setting}
                    【要求】：直接输出正文，禁止任何多余的寒暄。在正文输出完毕后，必须另起一行并严格以 `[AI_SUMMARY]` 作为分割符，然后输出约500字高度结构化的【本章复盘与记忆锚点】。
在 `[AI_SUMMARY]` 之后，必须严格按照以下3个维度输出（客观、精炼，纯作内部记忆使用）：
                    1. 核心剧情脉络：按时间顺序简述本章发生的实质性事件（起因、经过、结果）。
                    2. 人物状态更新：记录本章主角及配角的行为及心态。
                    3. 物品设定更新：记录本章所有物品状态
"""

                # 【修复3】强制优先使用用户手写的 synopsis (如果为空才退回使用 ai_synopsis)
                user_syn = chap.get("synopsis", "").strip()
                ai_syn = chap.get("ai_synopsis", "").strip()
                target_synopsis = user_syn if user_syn else (ai_syn if ai_syn else "无")

                user_prompt = f"【过往剧情轨迹参考】\n{history_str}\n\n"
                if prev_chapter_content.strip():
                    user_prompt += f"【紧接上一章的末尾内容】(参考此段过渡，但不要深陷其中)\n{prev_chapter_content.strip()}\n\n"

                # 【修复4】在末尾强调用叹号提升“本章要求”的权重
                user_prompt += f"""【本次写作核心任务 (最高优先级)】
                当前撰写：{vol['name']} - {chap['name']}
                本章必须实现的情节要求：{target_synopsis}

                【行动指令】
                请务必将剧情向【本章必须实现的情节要求】推进！不要被上一章的末尾内容困住，必须在本文中落实本章要求里的所有核心情节和名场面！扩写为文笔流畅的完整正文！"""

                response = self.client.chat.completions.create(
                    model=self.model,
                    temperature=self.temperature,
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    stream=True
                )

                content_buffer = ""
                for chunk in response:
                    if self._is_cancelled: break
                    delta = chunk.choices[0].delta
                    # 【新增】提取并发送 AI 的思考过程
                    reasoning = getattr(delta, "reasoning_content", None)
                    if reasoning:
                        self.reasoning_signal.emit(reasoning)
                    delta_content = getattr(delta, "content", None)
                    if delta_content:
                        content_buffer += delta_content
                        self.content_signal.emit(delta_content)  # 实时推送到界面

                if self._is_cancelled: return

                # 拆分正文与总结
                parts = content_buffer.split("[AI_SUMMARY]")
                main_content = parts[0].strip()
                ai_summary = parts[1].strip() if len(parts) > 1 else ""

                # 告诉主线程保存数据
                self.save_content_signal.emit(v_idx, c_idx, main_content, ai_summary)

class CorrectionWorker(QThread):
    # 信号定义
    status_signal = pyqtSignal(str)
    log_signal = pyqtSignal(str)  # 用于输出到右侧边栏的记录
    update_text_signal = pyqtSignal(int, int, str, str)  # v_idx, c_idx, new_content, new_summary
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    reasoning_signal = pyqtSignal(str)

    def __init__(self, api_key, base_url, model, temperature, project, scope, mode):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.project = project
        self.meta = project.meta
        self.scope = scope  # "full" 或 "chapter"
        self.mode = mode  # "typo", "setting", "all"
        # 章节级别纠错的坐标
        self.target_v_idx = -1
        self.target_c_idx = -1
        self._is_cancelled = False

    def set_target(self, v_idx, c_idx):
        self.target_v_idx = v_idx
        self.target_c_idx = c_idx

    def cancel(self):
        self._is_cancelled = True
        if hasattr(self, 'client'):
            try:
                self.client.close()
            except:
                pass

    def run(self):
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

            if self.scope == "chapter":
                self._correct_single_chapter(self.target_v_idx, self.target_c_idx, self.mode)
            elif self.scope == "full":
                self._correct_full_book(self.mode)

            # 无论是否被取消，正常退出时都向主界面发送信号，以恢复 UI 状态
            self.finished_signal.emit()
        except Exception as e:
            # 如果是手动取消引发的网络强行切断异常，直接无视并发送结束信号
            if self._is_cancelled:
                self.finished_signal.emit()
            else:
                self.error_signal.emit(str(e))

    def _call_llm_json(self, sys_prompt, user_prompt):
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt}
            ],
            stream=True  # 【修改处】强行开启流式传输以截获思考过程
        )

        content_buffer = ""
        for chunk in resp:
            if self._is_cancelled: break
            delta = chunk.choices[0].delta

            # 实时提取并发送思考过程到界面
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                self.reasoning_signal.emit(reasoning)

            # 缓冲后台的 JSON 正文
            content = getattr(delta, "content", None)
            if content:
                content_buffer += content

        if self._is_cancelled:
            return {}

        # 等待流式传输完毕后，再统一把缓冲区里的字符串解析为 JSON
        try:
            return json.loads(content_buffer)
        except json.JSONDecodeError as e:
            self.error_signal.emit(f"AI返回的JSON格式有误: {str(e)}")
            return {}

    def _correct_single_chapter(self, v_idx, c_idx, mode):
        vol = self.meta["volumes"][v_idx]
        chap = vol["chapters"][c_idx]
        content = self.project.read_chapter_content(vol["name"], chap["name"])
        ai_summary = chap.get("ai_synopsis", "")

        if not content.strip():
            self.status_signal.emit("⚠️ 当前章节无内容，跳过纠错。")
            return

        modes_to_run = ["typo", "setting"] if mode == "all" else [mode]
        current_content = content
        current_summary = ai_summary

        if "setting" in modes_to_run and not self._is_cancelled:
            self.status_signal.emit(f"🔍 正在进行【设定纠错】: {chap['name']}...")
            current_content, current_summary = self._do_setting_correction(v_idx, c_idx, current_content,
                                                                           current_summary)

        if "typo" in modes_to_run and not self._is_cancelled:
            self.status_signal.emit(f"📝 正在进行【错别字/语病纠错】: {chap['name']}...")
            current_content = self._do_typo_correction(v_idx, c_idx, current_content)

        # 统一保存
        self.update_text_signal.emit(v_idx, c_idx, current_content, current_summary)

    def _correct_full_book(self, mode):
        if mode in ["setting", "all"]:
            self.status_signal.emit("🕵️ 开启全书扫描模式，正在统筹全局设定...")
            # 第一阶段：排查有问题的章节
            problem_list = self._detect_global_setting_conflicts()
            if self._is_cancelled: return

            if not problem_list:
                self.log_signal.emit("✅ 全书设定逻辑严密，未发现吃书或设定矛盾现象！")
            else:
                self.log_signal.emit(f"⚠️ 扫描完毕，发现 {len(problem_list)} 个设定矛盾章节，准备逐一修复。")
                # 第二阶段：遍历修复
                for issue in problem_list:
                    if self._is_cancelled: break
                    v = issue.get("v_idx")
                    c = issue.get("c_idx")
                    reason = issue.get("reason")
                    vol_name = self.meta["volumes"][v]["name"]
                    chap_name = self.meta["volumes"][v]["chapters"][c]["name"]

                    self.status_signal.emit(f"🔧 正在修复设定矛盾: {vol_name}-{chap_name}...")
                    self.log_signal.emit(f"[{vol_name}-{chap_name}] 锁定错误: {reason}")

                    old_content = self.project.read_chapter_content(vol_name, chap_name)
                    old_summary = self.meta["volumes"][v]["chapters"][c].get("ai_synopsis", "")
                    new_content, new_summary = self._do_setting_correction(v, c, old_content, old_summary,
                                                                           specific_reason=reason)
                    self.update_text_signal.emit(v, c, new_content, new_summary)

        if mode in ["typo", "all"]:
            self.status_signal.emit("📝 开启全书错别字/语病排查...")
            for v_idx, vol in enumerate(self.meta["volumes"]):
                for c_idx, chap in enumerate(vol["chapters"]):
                    if self._is_cancelled: return
                    self.status_signal.emit(f"📝 正在校对: {vol['name']} - {chap['name']}...")
                    old_content = self.project.read_chapter_content(vol["name"], chap["name"])
                    if old_content.strip():
                        new_content = self._do_typo_correction(v_idx, c_idx, old_content)
                        summary = chap.get("ai_synopsis", "")
                        self.update_text_signal.emit(v_idx, c_idx, new_content, summary)

    def _do_typo_correction(self, v_idx, c_idx, content):
        sys_prompt = "你是一个火眼金睛的专业小说文字校对。你的任务是找出正文中的错别字和语病，并直接修改。必须返回严格的JSON。"
        user_prompt = f"""
请校对以下正文。
要求：
1. 修正错别字、标点错误、明显不通顺的语病。
2. 保持原作者的文风和网文特有的爽感表达，不要做不必要的润色和过度修改。

正文内容：
{content}

返回格式（严格JSON）：
{{
    "corrected_text": "完整的修正后的正文（必须完整包含所有段落）",
    "logs": ["发现[错别字/语病]：原句'...'，修改为'...'"]
}}
"""
        result = self._call_llm_json(sys_prompt, user_prompt)
        for log in result.get("logs", []):
            chap_name = self.meta["volumes"][v_idx]["chapters"][c_idx]["name"]
            self.log_signal.emit(f"✍️ [校对|{chap_name}] {log}")
        return result.get("corrected_text", content)

    def _do_setting_correction(self, v_idx, c_idx, content, summary, specific_reason=None):
        # 组装全局和局部大纲作为标准
        global_synopsis = self.meta.get("global_synopsis", "")
        vol = self.meta["volumes"][v_idx]
        chap = vol["chapters"][c_idx]

        # 【升级点1】：获取过往所有章节的剧情概要
        past_summaries = self._get_past_summaries(v_idx, c_idx)

        sys_prompt = "你是一个资深的网文主编，精通逻辑自洽和设定圆融。必须返回严格的JSON格式。"

        # 拼接豪华版上下文
        user_prompt = f"【全书总体设定与梗概】：\n{global_synopsis}\n\n"
        if past_summaries.strip():
            user_prompt += f"【过往剧情轨迹(防吃书基准)】：\n{past_summaries}\n\n"
        user_prompt += f"【本卷核心设定】：\n{vol.get('synopsis', '无')}\n\n"

        if specific_reason:
            # 【升级点2】：全局纠错传入了具体理由，要求结合前文详细扫描并修复
            user_prompt += f"【目标任务】：这是全局扫描发现的本章逻辑/设定错误。请结合上述【全书设定】和【过往剧情轨迹】，在下方正文中详细扫描并彻底修复该问题：\n{specific_reason}\n\n"
        else:
            # 单章纠错模式：让 AI 自己找茬并给出详细理由
            user_prompt += "【目标任务】：请仔细比对【过往剧情轨迹】和【全书设定】，检查下方正文中是否存在人物崩塌、前言不搭后语、逻辑矛盾（吃书现象，例如：死人复活未说明原因、物品归属错乱等）。请先给出详细的错误诊断理由，然后在正文中直接修复它们。\n\n"

        user_prompt += f"【当前章节正文】：\n{content}\n\n"
        user_prompt += f"【当前章原AI概要】：\n{summary}\n\n"

        # 【升级点3】：强制要求输出 error_reason 字段
        user_prompt += """
返回格式（严格JSON）：
{
    "has_issue": true/false, // 如果没有发现任何逻辑设定错误，返回false
    "error_reason": "详细的错误诊断理由。如果has_issue为true，必须说明正文具体哪里吃书或矛盾了，与前文哪一章冲突。如果为false则填无。",
    "corrected_text": "修复后的完整正文（如果无错误，原样返回）",
    "new_ai_summary": "如果正文剧情被修改，请同步更新AI概要（约500字，客观纪实结构化记录核心事件和伏笔）。如果无修改则原样返回。",
    "logs": ["发现[逻辑设定问题]：...，因此修改了..."] // 记录简要的纠错动作
}
"""
        result = self._call_llm_json(sys_prompt, user_prompt)

        if result.get("has_issue", False):
            # 将详细的诊断理由打印到 UI 的日志侧边栏中
            reason = result.get("error_reason", "")
            if reason and reason != "无":
                self.log_signal.emit(f"🕵️ [诊断报告|{chap['name']}] {reason}")

            for log in result.get("logs", []):
                self.log_signal.emit(f"🛠️ [设定修复|{chap['name']}] {log}")
            return result.get("corrected_text", content), result.get("new_ai_summary", summary)

        return content, summary

    def _detect_global_setting_conflicts(self):
        # 拼接全书梗概和卷章用户设纲
        sys_context = f"【全书全局大纲】\n{self.meta.get('global_synopsis', '')}\n\n"
        char_texts = [f"【{c['name']}】 性别:{c['gender']} 性格:{c['personality']} 经历:{c['experience']}" for c in
                      self.meta.get("characters", [])]
        sys_context += f"【核心人物设定】\n{chr(10).join(char_texts)}\n\n"

        # 拼接AI总结的所有章节概要
        all_summaries = ""
        for v_idx, vol in enumerate(self.meta["volumes"]):
            all_summaries += f"\n▶ 第{v_idx + 1}卷: {vol['name']}\n"
            for c_idx, chap in enumerate(vol["chapters"]):
                all_summaries += f"  - 第{c_idx + 1}章 [{chap['name']}]: {chap.get('ai_synopsis', '暂无概要')}\n"

        sys_prompt = f"你是一个网文剧情质检专家。这是本书的核心设定基石，请牢记：\n{sys_context}"
        user_prompt = f"""以下是AI总结的本书目前所有章节的剧情概要。
请排查是否存在：
1. 明显偏离【全局大纲】和【核心人物设定】的剧情。
2. 内部逻辑矛盾（吃书现象，例如：死人复活未说明原因、物品归属错乱、人物性格变化极大、人名串台）。

概要记录：
{all_summaries}

任务：定位存在严重矛盾和吃书现象的章节，并详细说明错因。
返回格式（严格JSON）：
{{
    "problematic_chapters": [
        {{
            "v_idx": 卷索引(整数，从0开始),
            "c_idx": 章索引(整数，从0开始),
            "reason": "详细说明错在哪里，与哪一部分设定或前面哪一章产生了矛盾"
        }}
    ]
}}
如果完全没有矛盾，"problematic_chapters"返回空数组。
"""
        result = self._call_llm_json(sys_prompt, user_prompt)
        return result.get("problematic_chapters", [])

    def _get_past_summaries(self, target_v_idx, target_c_idx):
        """获取目标章节之前的所有剧情概要（作为防吃书的记忆基准）"""
        history_str = ""
        for v_idx in range(target_v_idx + 1):
            vol = self.meta["volumes"][v_idx]
            history_str += f"\n▶ 第{v_idx + 1}卷: {vol['name']} (本卷梗概: {vol.get('synopsis', '无')})\n"

            # 限制章节遍历范围：如果是目标章节所在卷，只遍历到目标章节之前；如果是之前的卷，遍历整卷
            chap_limit = target_c_idx if v_idx == target_v_idx else len(vol["chapters"])
            for c_idx in range(chap_limit):
                chap = vol["chapters"][c_idx]
                # 优先读取 AI 之前生成的详细梗概，没有则读用户的
                ai_syn = chap.get("ai_synopsis", "")
                user_syn = chap.get("synopsis", "")
                display_syn = ai_syn if ai_syn.strip() else (user_syn if user_syn.strip() else "暂无概要")

                history_str += f"  - 第{c_idx + 1}章 [{chap['name']}]: {display_syn}\n"
        return history_str