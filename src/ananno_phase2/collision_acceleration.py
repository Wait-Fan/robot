"""Conservative local mesh proxies and exact box narrow-phase; SI units."""
import numpy as np


def local_bounds(model, mj):
    """Bounds in each geom frame, enclosing the imported collision convex hull.

    MuJoCo recenters mesh vertices on import; use compiled vertices together
    with geom_xpos/xmat, never the original STL or the link frame.
    """
    centers=np.zeros((model.ngeom,3))
    halves=np.repeat(np.asarray(model.geom_rbound)[:,None],3,axis=1)
    for i in range(model.ngeom):
        if model.geom_type[i]==mj.mjtGeom.mjGEOM_MESH:
            mesh=int(model.geom_dataid[i]);start=int(model.mesh_vertadr[mesh]);n=int(model.mesh_vertnum[mesh])
            vertices=model.mesh_vert[start:start+n]
            lo=vertices.min(axis=0);hi=vertices.max(axis=0)
            centers[i]=(lo+hi)/2;halves[i]=(hi-lo)/2
        elif model.geom_type[i]==mj.mjtGeom.mjGEOM_BOX:
            halves[i]=model.geom_size[i]
    # Float32 mesh vertices and transformed bounds must round outwards.
    return centers,halves+1e-7


def world_bounds(local_centers,local_halves,positions,rotations):
    rotations=np.asarray(rotations).reshape(-1,3,3)
    centers=positions+np.einsum('nij,nj->ni',rotations,local_centers)
    halves=np.einsum('nij,nj->ni',np.abs(rotations),local_halves)
    return centers,halves


def overlapping_pairs(centers,halves,first,second):
    """Outer AABB disjointness is sufficient only to skip a detailed check."""
    return np.all(np.abs(centers[first]-centers[second])<=halves[first]+halves[second],axis=1)


def box_overlap(ca,ra,ha,cb,rb,hb,tolerance=1e-5):
    # Same normalized 15 separating axes as the reference, evaluated together.
    a=ra.T;b=rb.T
    cross=np.cross(a[:,None,:],b[None,:,:]).reshape(9,3)
    axes=np.concatenate((a,b,cross))
    norms=np.linalg.norm(axes,axis=1);axes=axes[norms>=1e-10]/norms[norms>=1e-10,None]
    radius=np.abs(axes@ra)@ha+np.abs(axes@rb)@hb
    return bool(np.all(radius-np.abs(axes@(cb-ca))>tolerance))
