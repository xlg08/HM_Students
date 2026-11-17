"""Local prototype domain service. No network access or persistent storage."""
import copy
import hashlib
import json
import threading
import time
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from .config import Settings
from .connectors import CATALOG, fetch_metadata
from .tools import tool_catalog
from .observability import request_id


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex[:12]


class Problem(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


SAMPLES = {
    'jobs': [dict(title='Python 后端工程师', company='示例科技', location='上海', salary='25–35K/月'), dict(title='数据工程师', company='Demo Labs', location='新加坡', salary='6–9K SGD/月'), dict(title='AI 应用工程师', company='', location='远程', salary='面议')],
    'products': [dict(title='无线降噪耳机', price=699, currency='CNY', sku='DEMO-001'), dict(title='便携显示器', price=189, currency='USD', sku='DEMO-002'), dict(title='机械键盘', price=-1, currency='CNY', sku='DEMO-003')],
    'notices': [dict(title='关于开展数字产业项目申报的通知', publisher='示例产业服务中心', published_at='2026-11-17'), dict(title='人工智能应用试点征集公告', publisher='示例创新中心', published_at='2026-11-16'), dict(title='政策资料更新说明', publisher='', published_at='2026-11-15')],
}


class Service:
    def __init__(self, settings=None):
        self.settings = settings or Settings()
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=self.settings.workers, thread_name_prefix='capture')
        self.idempotency = {}
        self.sources, self.jobs, self.runs, self.records, self.audit = {}, {}, {}, {}, []
        for kind, name in [('jobs', '招聘样本源'), ('products', '商品样本源'), ('notices', '政策公告样本源')]:
            sid = uid()
            self.sources[sid] = dict(id=sid, name=name, kind=kind, status='ACTIVE', created_at=now(), mode='LOCAL_FIXTURE')
            jid = uid()
            self.jobs[jid] = dict(id=jid, name=name.replace('样本源', '监测'), source_id=sid, created_at=now())
        for connector, package in CATALOG.items():
            sid = uid()
            self.sources[sid] = dict(id=sid, name='PyPI / ' + package, kind='packages', status='DRAFT', created_at=now(), mode='PUBLIC_API', connector=connector, policy_url='https://docs.pypi.org/api/json/')
        self.log('SYSTEM_START', 'prototype', '内存模式启动，使用本地样本，不访问外网')

    def log(self, action, target, detail=''):
        self.audit.insert(0, dict(id=uid(), at=now(), action=action, target=target, detail=detail, actor='本地演示管理员', request_id=request_id.get()))
        del self.audit[self.settings.max_history:]

    def close(self):
        self.stopping.set()
        with self.lock:
            for run in self.runs.values():
                if run['status'] in ('QUEUED', 'RUNNING', 'PAUSED'):
                    run.update(status='CANCELLED', finished_at=now())
        self.executor.shutdown(wait=True, cancel_futures=True)

    def metrics(self):
        with self.lock:
            return dict(workers=self.settings.workers, capacity=self.settings.max_pending,
                        active_runs=sum(r['status'] in ('QUEUED', 'RUNNING', 'PAUSED') for r in self.runs.values()),
                        runs=len(self.runs), records=len(self.records), audit_events=len(self.audit),
                        stopping=self.stopping.is_set())

    def list_resource(self, resource, page=1, page_size=20, status='', query=''):
        if resource not in ('sources', 'jobs', 'runs', 'records', 'audit'):
            raise Problem('资源不存在', 404)
        if page < 1 or not 1 <= page_size <= 100:
            raise Problem('page 必须大于 0，page_size 必须在 1–100 之间')
        with self.lock:
            collection = getattr(self, resource)
            rows = list(collection.values()) if isinstance(collection, dict) else list(collection)
            rows = [r for r in rows if (not status or r.get('status') == status) and
                    (not query or query.lower() in json.dumps(r, ensure_ascii=False).lower())]
            rows.sort(key=lambda r: r.get('created_at', r.get('at', '')), reverse=True)
            offset = (page - 1) * page_size
            return copy.deepcopy(dict(items=rows[offset:offset + page_size], total=len(rows), page=page, page_size=page_size))

    def state(self):
        with self.lock:
            return copy.deepcopy(dict(sources=list(self.sources.values()), jobs=list(self.jobs.values()), runs=list(reversed(list(self.runs.values()))), records=list(self.records.values()), audit=self.audit, metrics=self.metrics(), tools=tool_catalog()))

    def get(self, collection, key):
        if not isinstance(key, str):
            raise Problem('资源 ID 必须为字符串')
        item = collection.get(key)
        if item is None:
            raise Problem('资源不存在', 404)
        return item

    def create_source(self, data):
        name = self.name(data)
        kind = data.get('kind')
        connector = data.get('connector', '')
        if connector:
            if not isinstance(connector, str) or connector not in CATALOG:
                raise Problem('???????')
            kind = 'packages'
        if not isinstance(kind, str) or kind not in (*SAMPLES, 'packages') or (kind == 'packages' and not connector):
            raise Problem('请选择支持的样本类型')
        with self.lock:
            if len(self.sources) >= self.settings.max_history:
                raise Problem('数据源数量达到本机演示容量上限', 409)
            sid = uid()
            self.sources[sid] = dict(id=sid, name=name, kind=kind, status='DRAFT', created_at=now(), mode='PUBLIC_API' if connector else 'LOCAL_FIXTURE', connector=connector)
            self.log('SOURCE_CREATE', sid, name)
            return self.sources[sid]

    @staticmethod
    def name(data):
        name = data.get('name')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise Problem('名称需要包含 1–80 个字符')
        return name.strip()

    def source_action(self, sid, action, data=None):
        with self.lock:
            source = self.get(self.sources, sid)
            transitions = {'approve': ('DRAFT', 'ACTIVE'), 'suspend': ('ACTIVE', 'SUSPENDED'), 'resume': ('SUSPENDED', 'ACTIVE')}
            if action not in transitions or source['status'] != transitions[action][0]:
                raise Problem('当前数据源状态不支持此操作', 409)
            if source['mode'] == 'PUBLIC_API' and action == 'approve':
                note = (data or {}).get('note', '')
                if not isinstance(note, str) or not note.strip():
                    raise Problem('?????? API ??????????')
                source['approval_note'] = note[:500]
            source['status'] = transitions[action][1]
            self.log('SOURCE_' + action.upper(), sid, '仅本地样本审批，不代表真实网站授权')
            return source

    def create_job(self, data):
        name = self.name(data)
        with self.lock:
            source = self.get(self.sources, data.get('source_id'))
            if len(self.jobs) >= self.settings.max_history:
                raise Problem('任务数量达到本机演示容量上限', 409)
            if source['status'] != 'ACTIVE':
                raise Problem('仅可选择已启用数据源', 409)
            jid = uid()
            self.jobs[jid] = dict(id=jid, name=name, source_id=source['id'], created_at=now())
            self.log('JOB_CREATE', jid, name)
            return self.jobs[jid]

    def start(self, jid, idempotency_key=None):
        with self.lock:
            job = self.get(self.jobs, jid)
            if self.stopping.is_set():
                raise Problem('服务正在关闭', 503)
            if idempotency_key is not None:
                if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
                    raise Problem('Idempotency-Key 长度须在 1–128 之间')
                prior = self.idempotency.get((jid, idempotency_key))
                if prior:
                    return copy.deepcopy(self.runs[prior])
            active = sum(r['status'] in ('QUEUED', 'RUNNING', 'PAUSED') for r in self.runs.values())
            if active >= self.settings.max_pending:
                raise Problem('运行队列已满，请稍后重试', 429)
            if len(self.runs) >= self.settings.max_history:
                raise Problem('批次达到本机历史容量上限，请重启或提高容量配置', 409)
            if self.sources[job['source_id']]['status'] != 'ACTIVE':
                raise Problem('来源未启用，禁止执行', 409)
            if any(r['job_id'] == jid and r['status'] in ('QUEUED', 'RUNNING', 'PAUSED') for r in self.runs.values()):
                raise Problem('此任务已有未结束批次', 409)
            rid = uid()
            run = dict(id=rid, job_id=jid, name=job['name'], source_id=job['source_id'], status='QUEUED', progress=0, created_at=now(), logs=[], count=0, error=None, request_id=request_id.get())
            self.runs[rid] = run
            if idempotency_key is not None:
                self.idempotency[(jid, idempotency_key)] = rid
            self.log('RUN_CREATE', rid, job['name'])
            self.executor.submit(self.execute, rid)
            return copy.deepcopy(run)

    def run_action(self, rid, action):
        with self.lock:
            run = self.get(self.runs, rid)
            allowed = {'pause': (('QUEUED', 'RUNNING'), 'PAUSED'), 'resume': (('PAUSED',), 'RUNNING'), 'cancel': (('QUEUED', 'RUNNING', 'PAUSED'), 'CANCELLED')}
            if action not in allowed or run['status'] not in allowed[action][0]:
                raise Problem('当前批次状态不支持此操作', 409)
            run['status'] = allowed[action][1]
            if action == 'cancel':
                run['finished_at'] = now()
            self.log('RUN_' + action.upper(), rid)
            return copy.deepcopy(run)

    def checkpoint(self, run):
        while True:
            with self.lock:
                if self.stopping.is_set() or run['status'] == 'CANCELLED':
                    return False
                if self.sources[run['source_id']]['status'] != 'ACTIVE':
                    raise Problem('数据源被停用，已终止批次')
                if run['status'] != 'PAUSED':
                    return True
            time.sleep(.1)

    def execute(self, rid):
        run = self.runs[rid]
        token = request_id.set(run['request_id'])
        try:
            source_snapshot = copy.deepcopy(self.sources[run['source_id']])
            real = source_snapshot['mode'] == 'PUBLIC_API'
            fetched = None
            for progress, message in [(10, '校验来源许可：本地样本通过'), (30, '读取本地原始 JSON 样本'), (55, '规则提取与字段证据定位'), (80, '必填字段与业务规则校验'), (100, '发布合格记录，异常记录进入复核')]:
                if real and progress == 30:
                    if not self.checkpoint(run):
                        return
                    fetched = fetch_metadata(source_snapshot['connector'])
                if real:
                    message = {10: '?? API ??????', 30: '??? PyPI ????', 55: '????????????', 80: '???????????', 100: '????????'}[progress]
                if self.stopping.wait(self.settings.stage_delay):
                    return
                while self.checkpoint(run):
                    with self.lock:
                        if run['status'] == 'CANCELLED':
                            return
                        if run['status'] == 'PAUSED':
                            continue
                        run['status'] = 'RUNNING'
                        run['progress'] = progress
                        run['logs'].append(dict(at=now(), message=message))
                        break
                else:
                    return
            # Recheck under the commit lock: cancellation cannot publish records.
            while self.checkpoint(run):
                with self.lock:
                    if run['status'] == 'PAUSED':
                        continue
                    if run['status'] == 'CANCELLED':
                        return
                    source = self.sources[run['source_id']]
                    if source['status'] != 'ACTIVE':
                        raise Problem('数据源被停用，禁止发布')
                    candidates = [fetched[0]] if real else SAMPLES[source['kind']]
                    if len(self.records) + len(candidates) > self.settings.max_history * 3:
                        raise Problem('记录数量达到本机容量上限')
                    for index, payload in enumerate(candidates):
                        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                        if any(r['source_id'] == source['id'] and r['hash'] == fingerprint for r in self.records.values()):
                            continue
                        issues = self.validate(source['kind'], payload)
                        key = uid()
                        evidence = copy.deepcopy(fetched[1]) if real else dict(uri='fixture://' + source['kind'] + '/' + str(index), pointer='/' + str(index), raw=copy.deepcopy(payload), extractor_version='fixture-rule-v1')
                        evidence['captured_at'] = now()
                        self.records[key] = dict(id=key, run_id=rid, source_id=source['id'], kind=source['kind'], payload=copy.deepcopy(payload), hash=fingerprint, mode=source['mode'], evidence=evidence, issues=issues, score=100 if not issues else 65, status='REVIEW' if issues else 'PUBLISHED', created_at=now())
                        run['count'] += 1
                    run.update(status='SUCCEEDED', progress=100, finished_at=now())
                    self.log('RUN_COMPLETE', rid, '新增记录 ' + str(run['count']) + ' 条（按来源和内容去重）')
                    return
        except Exception as exc:
            logging.getLogger('aicrawl').exception('capture_failed')
            with self.lock:
                if run['status'] != 'CANCELLED':
                    run.update(status='FAILED', error=str(exc), finished_at=now())
                    self.log('RUN_FAILED', rid, str(exc))
        finally:
            request_id.reset(token)

    @staticmethod
    def validate(kind, payload):
        required = {'jobs': ['title', 'company', 'location'], 'products': ['title', 'sku', 'currency'], 'notices': ['title', 'publisher', 'published_at'], 'packages': ['title', 'package', 'version', 'source_url']}[kind]
        issues = ['缺少必填字段：' + k for k in required if not payload.get(k)]
        if kind == 'products' and (not isinstance(payload.get('price'), (int, float)) or payload['price'] <= 0):
            issues.append('价格必须大于 0')
        return issues

    def review(self, key, data):
        with self.lock:
            record = self.get(self.records, key)
            if record['status'] != 'REVIEW':
                raise Problem('记录已经复核', 409)
            decision = data.get('decision')
            note = data.get('note', '')
            if decision not in ('reject', 'approve') or not isinstance(note, str) or not note.strip():
                raise Problem('请选择复核决定并填写理由')
            if decision == 'approve' and record['issues']:
                raise Problem('硬性校验未通过，不能发布；请驳回并修复源数据后重新采集', 409)
            record.update(status='REJECTED' if decision == 'reject' else 'PUBLISHED', review_note=note[:500])
            self.log('RECORD_REVIEW', key, note[:500])
            return record
