"""Checked joint shortcutting and C2 quintic time parameterization.

Curve checks are discrete, at a bounded joint displacement resolution. They
do not assert exact continuous collision detection or global optimality.
"""
import math
import numpy as np


def _coefficients(left,right):
    duration=float(right['time_from_start']-left['time_from_start'])
    q0,q1=np.asarray(left['positions']),np.asarray(right['positions']);dq=q1-q0
    v0,v1=np.asarray(left['velocities']),np.asarray(right['velocities'])
    a0=np.asarray(left.get('accelerations',np.zeros_like(q0)))
    a1=np.asarray(right.get('accelerations',np.zeros_like(q1)))
    return np.array([q0,v0*duration,.5*a0*duration**2,
        10*dq-(6*v0+4*v1)*duration-(1.5*a0-.5*a1)*duration**2,
        -15*dq+(8*v0+7*v1)*duration+(1.5*a0-a1)*duration**2,
        6*dq-3*(v0+v1)*duration-(.5*a0-.5*a1)*duration**2]),duration


def evaluate_segment(left,right,fraction):
    coefficients,duration=_coefficients(left,right)
    u=float(np.clip(fraction,0,1))
    values=[]
    for order in range(3):
        derivative=np.polynomial.polynomial.polyder(coefficients,m=order,axis=0)
        values.append(np.polynomial.polynomial.polyval(u,derivative)/duration**order)
    return tuple(values)


def _extrema(coefficients,derivative_order):
    derivative=np.polynomial.polynomial.polyder(coefficients,m=derivative_order,axis=0)
    next_derivative=np.polynomial.polynomial.polyder(derivative,axis=0)
    low=[];high=[]
    for axis in range(coefficients.shape[1]):
        roots=np.polynomial.polynomial.polyroots(next_derivative[:,axis])
        samples=[0.,1.]+[float(r.real) for r in roots if abs(r.imag)<1e-9 and 0<r.real<1]
        values=np.polynomial.polynomial.polyval(samples,derivative[:,axis])
        low.append(min(values));high.append(max(values))
    return np.asarray(low),np.asarray(high)


def smooth_trajectory(path,velocity,acceleration,valid,*,lower,upper,resolution=.035,
                      shortcut=True,cancelled=None,segment_valid=None):
    path=np.asarray(path,dtype=float);velocity=np.asarray(velocity,dtype=float);acceleration=np.asarray(acceleration,dtype=float)
    lower,upper=np.asarray(lower),np.asarray(upper)
    if path.ndim!=2 or len(path)<2 or path.shape[1:]!=velocity.shape or velocity.shape!=acceleration.shape or lower.shape!=velocity.shape or upper.shape!=velocity.shape:
        raise ValueError('Invalid trajectory dimensions')
    if not np.isfinite(path).all() or not np.isfinite(velocity).all() or not np.isfinite(acceleration).all() or np.any(velocity<=0) or np.any(acceleration<=0) or not math.isfinite(resolution) or resolution<=0:
        raise ValueError('Invalid trajectory limits')
    def check():
        if cancelled is not None and cancelled():raise InterruptedError('Trajectory smoothing cancelled')
    def state(q):
        check()
        return bool(np.all(q>=lower-1e-10) and np.all(q<=upper+1e-10) and valid(q))
    def edge(a,b):
        count=max(1,int(math.ceil(np.max(np.abs(b-a))/resolution)))
        return all(state(a+(b-a)*i/count) for i in range(count+1))
    if not all(state(q) for q in path):raise ValueError('Trajectory waypoint in collision or outside joint limits')
    # Remove exact duplicates without introducing a jump.
    path=path[np.r_[True,np.max(np.abs(np.diff(path,axis=0)),axis=1)>1e-12]]
    if len(path)==1:path=np.vstack([path,path])
    if shortcut and len(path)>2:
        reduced=[path[0]];index=0
        while index<len(path)-1:
            check();last=len(path)-1
            candidates=sorted(set([index+1,last]+np.linspace(index+1,last,min(10,last-index),dtype=int).tolist()),reverse=True)
            target=next((j for j in candidates if edge(path[index],path[j])),None)
            if target is None:raise ValueError('Trajectory edge in collision')
            reduced.append(path[target]);index=target
        path=np.asarray(reduced)
    delta=np.diff(path,axis=0)
    durations=np.maximum(.01,np.maximum(np.max(1.9*np.abs(delta)/velocity,axis=1),np.sqrt(np.max(6*np.abs(delta)/acceleration,axis=1))))
    for blend in (1.,.5,.25,0.):
        check();speeds=np.zeros_like(path)
        secants=delta/durations[:,None]
        for i in range(1,len(path)-1):
            same=secants[i-1]*secants[i]>0
            speeds[i,same]=blend*2/(1/secants[i-1,same]+1/secants[i,same])
        points=[];elapsed=0.
        for i,q in enumerate(path):
            points.append({'time_from_start':float(elapsed),'positions':q.tolist(),'velocities':speeds[i].tolist(),'accelerations':np.zeros_like(q).tolist()})
            if i<len(durations):elapsed+=durations[i]
        # Exact polynomial derivative extrema set a uniform time stretch. This
        # preserves each geometric curve and C2 knot continuity.
        stretch=1.
        for left,right in zip(points,points[1:]):
            coefficients,duration=_coefficients(left,right)
            vlo,vhi=_extrema(coefficients,1);alo,ahi=_extrema(coefficients,2)
            stretch=max(stretch,float(np.max(np.maximum(abs(vlo),abs(vhi))/duration/velocity)),
                        float(np.sqrt(np.max(np.maximum(abs(alo),abs(ahi))/duration**2/acceleration))))
        stretch*=1.000001
        for point in points:
            point['time_from_start']*=stretch
            point['velocities']=(np.asarray(point['velocities'])/stretch).tolist()
        clear=True
        for left,right in zip(points,points[1:]):
            coefficients,_=_coefficients(left,right)
            qlow,qhigh=_extrema(coefficients,0)
            if np.any(qlow<lower-1e-10) or np.any(qhigh>upper+1e-10):clear=False;break
            vlo,vhi=_extrema(coefficients,1)
            count=max(2,int(math.ceil(np.max(np.maximum(abs(vlo),abs(vhi)))/resolution)))
            for u in np.linspace(0,1,count+1):
                q=evaluate_segment(left,right,u)[0]
                if not state(q) or (segment_valid is not None and not segment_valid(q,np.asarray(left['positions']),np.asarray(right['positions']))):
                    clear=False;break
            if not clear:break
        if clear:return points
    raise ValueError('No collision-free smoothed trajectory within joint/Cartesian limits')
