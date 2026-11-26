"""Cooperative whole-job deadline and durable diagnostics, independent of Qt."""
from contextlib import AbstractContextManager
from dataclasses import asdict,is_dataclass
from datetime import datetime
from functools import wraps
import inspect
import json
import math
from pathlib import Path
import threading
import time

from .packer import PackingCancelled


class PackingTimedOut(TimeoutError):
    """The computation budget expired; this is neither success nor proof of infeasibility."""


class RobotPlanningIncomplete(RuntimeError):
    """Local motion search remains unknown; do not reject the packing layout."""


class JobMonitor(AbstractContextManager):
    def __init__(self,output_dir,*,max_seconds=3600.,log=None,progress=None,cancelled=None,
                 request=None,heartbeat_seconds=5.):
        self.max_seconds=float(max_seconds);self.heartbeat_seconds=float(heartbeat_seconds)
        if not math.isfinite(self.max_seconds) or self.max_seconds<=0:raise ValueError('总计算时限必须为有限正数')
        if not math.isfinite(self.heartbeat_seconds) or self.heartbeat_seconds<=0:raise ValueError('心跳间隔必须为有限正数')
        self.directory=Path(output_dir).resolve();self.log_path=self.directory/'run.log'
        self.status_path=self.directory/'run_status.json'
        self.forward_log=log;self.forward_progress=progress;self.user_cancelled=cancelled
        self.request=request or {};self.started=time.monotonic();self.started_at=datetime.now().astimezone().isoformat()
        self.last_event='读取输入与初始化';self.processed_boxes=0;self.total_boxes=None
        self._lock=threading.RLock();self._stop=threading.Event();self._thread=None;self._file=None
        self._closed=False;self._active=False;self._last_write=0.;self._heartbeat_error=None

    def __enter__(self):return self

    def _activate(self):
        if self._active:return
        self.directory.mkdir(parents=True,exist_ok=True)
        self._file=self.log_path.open('a',encoding='utf-8',buffering=1);self._active=True
        self._line(f'任务开始；总时限 {self.max_seconds/60:g} 分钟；参数 '+json.dumps(self.request,ensure_ascii=False,default=str))
        self._write_status('running',force=True)
        self._thread=threading.Thread(target=self._heartbeat,name='packing-job-heartbeat',daemon=True);self._thread.start()

    def _line(self,message):
        self._file.write(f'[{datetime.now().astimezone().isoformat(timespec="seconds")}] {message}\n')

    def _write_status(self,status,*,force=False,error=None):
        now=time.monotonic()
        if not force and now-self._last_write<.5:return
        payload={'schema_version':1,'status':status,'completed':status=='completed','started_at':self.started_at,
            'max_seconds':self.max_seconds,'elapsed_seconds':now-self.started,'last_event':self.last_event,
            'processed_boxes':self.processed_boxes,'total_boxes':self.total_boxes,'request':self.request,
            'log_file':self.log_path.name,'error':str(error) if error is not None else None}
        temporary=self.status_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        temporary.replace(self.status_path);self._last_write=now

    def log(self,message):
        with self._lock:
            if self._closed:return
            self.last_event=str(message);self._activate();self._line(message);self._write_status('running')
            if self.forward_log:self.forward_log(str(message))

    def progress(self,done,total):
        with self._lock:
            if self._closed:return
            self.processed_boxes=int(done);self.total_boxes=int(total)
            if self._active:self._write_status('running')
            if self.forward_progress:self.forward_progress(done,total)

    def cancelled(self):
        if self.user_cancelled and self.user_cancelled():return True
        if self._heartbeat_error is not None:raise RuntimeError('运行日志写入失败：'+str(self._heartbeat_error)) from self._heartbeat_error
        if time.monotonic()-self.started>=self.max_seconds:
            raise PackingTimedOut(f'达到总计算时限 {self.max_seconds/60:g} 分钟，本次未完成；不代表装箱无解。日志：{self.log_path}')
        return False

    def _heartbeat(self):
        while not self._stop.wait(self.heartbeat_seconds):
            try:
                with self._lock:
                    if self._closed:return
                    elapsed=time.monotonic()-self.started
                    message=f'任务进度：已运行 {elapsed:.0f} / {self.max_seconds:.0f} 秒；{self.last_event}'
                    if elapsed>=self.max_seconds:message+='；已到总时限，等待当前操作安全退出'
                    self._line(message);self._write_status('running',force=True)
                    if self.forward_log:self.forward_log(message)
            except Exception as exc:
                self._heartbeat_error=exc;return

    def __exit__(self,kind,error,traceback):
        self._stop.set()
        with self._lock:
            self._closed=True
            if not self._active and isinstance(error,(PackingTimedOut,PackingCancelled)):self._activate()
            if self._active:
                status='completed' if error is None else 'validation_pending' if isinstance(error,RobotPlanningIncomplete) else 'timed_out' if isinstance(error,PackingTimedOut) else 'cancelled' if isinstance(error,PackingCancelled) else 'failed'
                message={'completed':'任务完成','validation_pending':'机器人局部规划未完成，未判定垛型不可行','timed_out':'任务超时，本次未完成','cancelled':'用户已停止，本次未完成','failed':'任务失败，本次未完成'}[status]
                self._line(message+('：'+str(error) if error is not None else ''))
                self._write_status(status,force=True,error=error);self._file.close()
        if self._thread is not None and self._thread is not threading.current_thread():self._thread.join(timeout=2.)
        return False


def monitored_job(function):
    signature=inspect.signature(function)
    @wraps(function)
    def wrapped(*args,**kwargs):
        bound=signature.bind(*args,**kwargs);bound.apply_defaults();values=bound.arguments
        request={key:(asdict(value) if is_dataclass(value) else str(value.resolve()) if isinstance(value,Path) else value)
                 for key,value in values.items() if key not in ('log','progress','cancelled')}
        request['dataset']=str(Path(values['dataset']).resolve())
        with JobMonitor(values['output_dir'],max_seconds=values['max_seconds'],request=request,
                        log=values['log'],progress=values['progress'],cancelled=values['cancelled']) as monitor:
            values.update(log=monitor.log,progress=monitor.progress,cancelled=monitor.cancelled)
            return function(*bound.args,**bound.kwargs)
    return wrapped
