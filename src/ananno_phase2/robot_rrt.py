"""Deterministic, bounded bidirectional RRT-Connect with checked joint edges."""
import math
import time
import numpy as np

def rrt_connect(start, goal, lower, upper, valid, *, seed=1, max_iterations=2000,
                step=.18, resolution=.035, seconds=3., cancelled=None,diagnostics=None):
    details=diagnostics if diagnostics is not None else {}
    details.update(status='search_exhausted',seed=seed,iterations=0,blocked_samples=0)
    start,goal,lower,upper=map(lambda x:np.asarray(x,dtype=float),(start,goal,lower,upper))
    if not (start.shape==goal.shape==lower.shape==upper.shape) or start.ndim!=1:
        raise ValueError('Joint vectors must have matching one-dimensional shapes')
    if not all(np.all(np.isfinite(v)) for v in (start,goal,lower,upper)) or np.any(lower>=upper):
        raise ValueError('Invalid joint values or bounds')
    if min(step,resolution,seconds)<=0 or not all(math.isfinite(x) for x in (step,resolution,seconds)):
        raise ValueError('Planner budgets must be finite and positive')
    def state(q):return bool(np.all(q>=lower) and np.all(q<=upper) and valid(q))
    if not state(start):details['status']='start_state_invalid';return None
    if not state(goal):details['status']='goal_state_invalid';return None
    deadline=time.monotonic()+seconds
    def check_budget():
        if cancelled is not None and cancelled():raise InterruptedError('Robot planning cancelled')
        return time.monotonic()<deadline
    def edge(a,b):
        count=max(1,int(math.ceil(np.max(np.abs(b-a))/resolution)))
        for i in range(1,count+1):
            if not check_budget():details['status']='budget_exhausted';return False
            if not state(a+(b-a)*i/count):details['blocked_samples']+=1;return False
        return True
    if edge(start,goal):details['status']='verified_path';return [start.tolist(),goal.tolist()]
    rng=np.random.default_rng(seed)
    a,pa,b,pb=[start],[-1],[goal],[-1];swapped=False
    def extend(nodes,parents,target):
        index=min(range(len(nodes)),key=lambda i:float(np.linalg.norm(nodes[i]-target)))
        delta=target-nodes[index];length=float(np.linalg.norm(delta))
        q=target.copy() if length<=step else nodes[index]+delta*step/length
        if not edge(nodes[index],q):return None,False
        nodes.append(q);parents.append(index)
        return len(nodes)-1,length<=step
    def backtrace(nodes,parents,index):
        path=[]
        while index>=0:path.append(nodes[index].tolist());index=parents[index]
        return path[::-1]
    for iteration in range(max_iterations):
        details['iterations']=iteration+1
        if not check_budget():details['status']='budget_exhausted';break
        target=b[0] if rng.random()<.1 else rng.uniform(lower,upper)
        ia,_=extend(a,pa,target)
        if ia is not None:
            while check_budget():
                ib,reached=extend(b,pb,a[ia])
                if ib is None:break
                if reached:
                    path=backtrace(a,pa,ia)+backtrace(b,pb,ib)[::-1][1:]
                    details['status']='verified_path';return path[::-1] if swapped else path
        a,b,pa,pb=b,a,pb,pa;swapped=not swapped
    return None
