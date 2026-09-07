"""Versioned, model-neutral measurement contract for the paired frontier suite."""
from __future__ import annotations

import copy

VERSION = '5.0.0'

EVENT_CONTRACT = '''
## Complete interoperability contract (v5.0)

- Versions are zero-based; an empty stream's expected_version is -1. A stale
  legal version raises ConcurrencyError. Values below -1 may raise ValueError.
- append returns the committed version list. Identical global command_id,
  stream and canonical-JSON events replay the original list even after reopen;
  different content/stream with that id raises ValueError. Dict key order is
  irrelevant. Serialization failure must leave the whole batch uncommitted.
- read returns ordered records {"version": int, "payload": original_value}.
  A lossless flattened dictionary plus version is also accepted. It must not
  replace the original payload with its JSON serialization or add fields to it.
- Legacy events(stream,version,payload) contains JSON text. Migrate losslessly,
  reconstruct integrity metadata and permit subsequent appends. events must
  expose checksum or both prev_hash and event_hash; commands exposes command_id.
- save_snapshot keeps history. Saving below the highest saved version raises
  ValueError or ConcurrencyError, even if a later row has become corrupt.
  load_snapshot returns {"version": int, "state": decoded_value}, or None when
  no valid row exists. Corrupt newest rows fall back to the latest intact row.
- A process kill during append may leave the entire batch or none, never a
  partial batch. Recovery must support fresh writes and replay. Hash chains
  must detect altered payloads; read raises IntegrityError on corruption.
'''


def optimize_case(definition: dict) -> dict:
    """Apply only to the selected non-frontend suite, before revision freezing."""
    item = copy.deepcopy(definition)
    dimension = (item.get('metadata') or {}).get('capability_dimension')
    if not dimension or dimension == 'creative_frontend':
        return item
    item['version'] = VERSION
    meta = item['metadata']
    meta.update(validation_pairing='experiment-case-repetition/v1',
                measurement_version=VERSION, score_basis='quality_only',
                primary_score='frontier_quality', reliability_reporting='first_attempt_separate')
    meta['score_scale'] = [[0,0],[40,24],[60,42],[70,54],[80,67],[90,80],[95,89],[98,95],[100,100]]
    # One unaided submission for both models; self-testing inside the task is
    # allowed. No hidden-feedback retries multiplied into the ability score.
    item['attempt_policy'] = {'max_attempts': 1, 'pass_threshold': 85,
                              'preserve_workspace': True}
    meta.pop('quality_weight', None)
    meta.pop('time_weight', None)
    item['instruction'] += (
        '\n\n评测协议 v5：按公开义务分项评分；允许在提交前自行测试和修复。'
        '正式隐藏评分只有一次，不提供隐藏失败后的重做机会。'
        '耗时、Token 与原始义务完成分单列；主分保留公开的 frontier_v1 掌握度刻度。'
        '平台故障进入待复核，不作为候选能力为零。'
    )
    if dimension == 'mathematical_reasoning':
        item['instruction'] += '\n涉及三维坐标时用 α=(a1,a2,a3)^T；结果字段支持等价表达式，证明不得省略。'
        for variant in (item.get('_private_frontier_variants') or {}).get('variants', []):
            variant['instruction'] += item['instruction'][item['instruction'].find('\n\n评测协议 v5：'):]
    elif dimension == 'research_writing':
        item['instruction'] += (
            '\nclaims.json 可为数组或 {"claims":[...]}。id 必须为非空唯一字符串；'
            'depends_on 为已有主张 id 字符串数组，不得有自环或循环，根节点用 []。'
            '计算结果应标 inference，不强制沿用来源的显示单位，但转换公式必须可复算。'
            '提交 analysis.py，执行 python analysis.py --verify 必须只校验、不修改交付文件，'
            '独立复算报告的核心估值/预算、至少三个翻转阈值、联合压力网格、两项信息价值；'
            '裁判须独立检查公式与输入，不能仅凭脚本输出 PASS 给分。'
            '对不可识别的概率应给区间/部分识别结论，不能把任意点估计伪装成资料事实。'
        )
        for validator in item['validators']:
            if validator['type'] == 'research_claims':
                validator['config']['require_claim_graph'] = True
                validator['weight'] = 32
            if validator['type'] == 'ai_rubric':
                validator['config']['criteria'].append(
                    '独立复算 analysis.py 与三个产物；逐个查找假设偷换、不可识别量伪精确、'
                    '来源依赖重复计权、尾部约束和调查信息价值。脚本自身声明 PASS 不构成独立证据。')
        item['validators'].append({'type':'file_exists','weight':2,'config':{'path':'analysis.py'}})
    elif dimension == 'agent_execution' and 'event-store' in item['slug']:
        item['initial_files']['SPEC.md'] += EVENT_CONTRACT
    elif dimension == 'agent_execution':
        item['instruction'] = item['instruction'].replace('中型按 2% 差距线评分', '中型按 0.5% 满分容差评分')
        item['instruction'] += (
            '\n任务、机器和模式 ID 是不透明标识；输入数组不保证拓扑/优先级顺序。'
            '每次隐藏求解限 150 秒，共运行两次检查确定性。'
            'makespan 满分相对容差依小/中/大/宽/深为 0/0.5%/2%/4%/6%；'
            '中/大/宽/深的该项分数分别在差距10%/14%/18%/22%处降为零。'
            '解质量中 makespan 占80%，非可再生资源与加权完成时间差距合计占20%；'
            '可行性和约束正确性独立评分。')
    elif dimension == 'systems_backend':
        # The existing time target is advisory, not an assessment of quality.
        item['limits']['max_runtime_seconds'] = 14400
        if 'task-queue' in item['slug']:
            item['instruction'] += (
                '\nHTTP maintenance/expire 接受 JSON {"now": optional_timestamp}；'
                '时间戳支持与 Python API 相同的有限 Unix 秒数或 ISO-8601 字符串。'
                '省略 now 使用当前 UTC。响应为 JSON；expire_leases 返回非负整数。\n')
    return item
