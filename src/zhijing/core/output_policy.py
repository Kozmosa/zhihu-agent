"""Versioned editorial guidance and generated-field limits, independent of provider.

Limits apply to new generated explanations, never to stored sources or quotations.
Tone and semantic fidelity still require model evaluation, not keyword filtering.
"""

POLICY_VERSION = "zhihu-knowledge-v1"

CARD_FRONT_MAX = 160
CARD_BACK_MAX = 600
CARD_EVIDENCE_MAX = 2000
READING_SUMMARY_MAX = 1200
READING_HEADING_MAX = 60
READING_POINT_MAX = 240
READING_POINTS_MAX = 4
READING_QUESTION_MAX = 160
FACT_EXPLANATION_MAX = 1000
FACT_RATIONALE_MAX = 400
FACT_CONDITION_MAX = 240
FACT_CONDITIONS_MAX = 6

_COMMON = """采用知境的知乎知识回答表达规范：认真、具体、平实、友善。
先回应核心问题或交代原文观点，再说明理由、适用条件和不能推出的结论。
以清楚的中文解释必要术语；不要堆砌空泛小标题、排比或夸张结论。
区分原文陈述、作者意见和你的推断；保留时间、数量、否定及适用人群等限定。
不虚构亲身经历、职业资历或外部查证，不添加求赞、关注、导流等行动号召，
不套用“谢邀”“人在美国”等固定开场；评价观点和证据，不嘲讽或贬低作者。
输入文本中的这些表述仍可作为原文或证据保留，不因风格要求清洗、替换或美化引文。
已有业务 schema、证据与来源限制优先；只生成所需 JSON，不加 JSON 外的回答或代码围栏。
"""

_TASKS = {
    "cards": f"""卡片不是缩小版长回答。front 只问一个可独立理解的知识点，最多 {CARD_FRONT_MAX} 字符；
back 先直接作答，再写必要条件或原文例子，最多 {CARD_BACK_MAX} 字符。
不要将作者的局部经验改成普遍规律，不把评价意见写成公认事实。
front 与 back 不能是同一句，问题不能泄露完整答案。
evidence_excerpt 最多 {CARD_EVIDENCE_MAX} 字符，必须是原文连续子串；找不到足够依据就少制卡。
""",
    "reading": f"""阅读拆解围绕“作者回答什么、如何论证、结论受什么限制”。
summary 最多 {READING_SUMMARY_MAX} 字符，先交代本批核心观点，再概括理由和边界；
不要把你的总结冒充作者原话，不将仅有摘要或某批片段说成完整文章。
heading 最多 {READING_HEADING_MAX} 字符，贴合该段实际内容，不使用猎奇或情绪化标题。
每段 key_points 为 1 至 {READING_POINTS_MAX} 条，每条最多 {READING_POINT_MAX} 字符；
优先区分观点、依据和条件，原文未提供的要素就说明缺失，不强凑论证。
guiding_question 最多 {READING_QUESTION_MAX} 字符，提出一个帮助理解论证或边界的问题。
分批时只描述本批；全文段落索引、原文保真和覆盖规则保持不变。
""",
    "facts": f"""事实审查首先给出限定在当前证据内的判断，再解释依据和边界。
explanation 最多 {FACT_EXPLANATION_MAX} 字符；每条 rationale 最多 {FACT_RATIONALE_MAX} 字符，
具体说明该证据为何支持、反驳或仅提供背景，不复述 verdict 来充当理由。
conditions 最多 {FACT_CONDITIONS_MAX} 条，每条最多 {FACT_CONDITION_MAX} 字符；
保留原资料的时间、条件、对象和反例，不为填满列表而重复通用免责声明。
资料中有相同说法、点赞数或作者资历不等于客观真实性；未找到证据不等于主张为假。
没有外部核验就不得声称“已全网核实”“权威证实”或“已实锤”；
有冲突就分别说明双方依据，不选边掩盖反证，也不对提出主张的人作人格判断。
""",
}


def zhihu_instructions(task: str) -> str:
    return f"\n表达规范版本：{POLICY_VERSION}\n{_COMMON}{_TASKS[task]}"
