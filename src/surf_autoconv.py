from gpaw import GPAW
from ase.constraints import FixAtoms
from ase import build
from ase.io import write
from ase.db import connect
import os
import optimizer as opt
from ase.parallel import parprint
import numpy as np
import re
import sys
import time

def surf_auto_conv(element,struc,init_layer=3,vac=5,fix_layer=2,h=0.14,k=6,xc='PBE',sw=0.1,rela_tol=10*10**(-3),temp_print=True):
    dispatcher = {'fcc100':build.fcc100,'fcc110':build.fcc110,'fcc111':build.fcc111,
                  'bcc100':build.bcc100,'bcc110':build.bcc110,'bcc111':build.bcc111,
                  }
    m_ind=re.findall(r'\d+',struc)[0]
    try:
        db_bulk=connect(element+'/'+'bulk'+'/'+'sw_converge.db')
        opt_bulk=db_bulk.get_atoms(id=len(db_bulk)-2)
        opt_bulk_e=opt_bulk.get_potential_energy()
        a=opt_bulk.get_cell()[0][1]*2
        parprint('Lattice Constant = ',np.round(a,decimals=5))
        parprint('Potential Energy = ',np.round(opt_bulk_e,decimals=5))
    except:
        parprint('ERROR: No Optimized Bulk Object Found!')
        parprint('Surface Convergence Computation Suspended!')
        sys.exit()
    db_surf=connect(element+'/'+'surf'+'/'+'layer_converge.db')

    #first optimize the layers
    diff_primary=100
    diff_second=100
    iters=0
    layer_ls=[]
    while (diff_primary>rela_tol or diff_second>rela_tol) and iters <= 6:
        slab = dispatcher[struc](element, size=(1, 1, init_layer),a=a,vacuum=vac)
        fix_mask=slab.positions[:,2] <= np.unique(slab.positions[:,2])[fix_layer-1]
        slab.set_constraint(FixAtoms(mask=fix_mask))
        slab.set_pbc([1,1,0])
        calc=GPAW(xc=xc,
            h=h,
            symmetry = {'point_group': False},
            kpts=(k,k,1),
            occupations={'name': 'fermi-dirac','width': sw},
            poissonsolver={'dipolelayer': 'xy'})
        slab.set_calculator(calc)
        location=element+'/'+'surf'+'/'+m_ind+'/'+str(init_layer)+'x1x1'
        opt.surf_relax(slab, location, fmax=0.01, maxstep=0.04, replay_traj=None)
        db_surf.write(slab,layers=init_layer)
        if iters>=2:
            fst=db_surf.get_atoms(id=iters-1)
            snd=db_surf.get_atoms(id=iters)
            trd=db_surf.get_atoms(id=iters+1)
            diff_primary=max(surf_e_calc(fst,snd,opt_bulk_e),surf_e_calc(fst,trd,opt_bulk_e))
            diff_second=surf_e_calc(snd,trd,opt_bulk_e)
            temp_output_printer(db_surf,iters,'layers',opt_bulk_e,temp_print)
            
            #diff_primary, diff_second=surf_e_converge_calc(fst,snd,trd,opt_bulk_e)
        layer_ls.append(init_layer)
        iters+=1
        init_layer+=1
    if iters>=6:
        if diff_primary>rela_tol or diff_second>rela_tol:
            parprint('WARNING: Max Layer Íiterations reached! System may not converged.')
            #parprint("Possible Error: Incorrect Lattice Parameters, Inappropriate Starting Grid Size.")
            parprint('Computation Suspended!')
            sys.exit()
    layer=layer_ls[-3]

    #second optimize the vaccum layer
    db_vac=connect(element+'/'+'surf'+'/'+'vac_converge.db')
    diff_primary=100
    diff_second=100
    iters=0
    vac_ls=[]
    time_ls=[]
    while (diff_primary>rela_tol or diff_second>rela_tol) and iters <= 5:
        if iters>1:
            if np.diff(time_ls)[-1]>0 and (diff_primary<rela_tol and diff_second<rela_tol):
                break
        slab = dispatcher[struc](element, size=(1, 1, layer),a=a,vacuum=vac)
        fix_mask=slab.positions[:,2] <= np.unique(slab.positions[:,2])[fix_layer-1]
        slab.set_constraint(FixAtoms(mask=fix_mask))
        slab.set_pbc([1,1,0])
        calc=GPAW(xc=xc,
            h=h,
            symmetry = {'point_group': False},
            kpts=(k,k,1),
            occupations={'name': 'fermi-dirac','width': sw},
            poissonsolver={'dipolelayer': 'xy'})
        slab.set_calculator(calc)
        location=element+'/'+'surf'+'/'+m_ind+'/'+'layer_optimized'+'/'+'vacuum_'+str(vac)
        start_t=time.time()
        opt.surf_relax(slab, location, fmax=0.01, maxstep=0.04, replay_traj=None)
        end_t=time.time()
        period=np.round(end_t-start_t,decimals=5)
        time_ls.append(period)
        db_vac.write(slab,vac=vac)
        if iters>=2:
            fst=db_vac.get_atoms(id=iters-1)
            snd=db_vac.get_atoms(id=iters)
            trd=db_vac.get_atoms(id=iters+1)
            diff_primary=max(surf_e_calc(fst,snd,opt_bulk_e),surf_e_calc(fst,trd,opt_bulk_e))
            diff_second=surf_e_calc(snd,trd,opt_bulk_e)
            temp_output_printer(db_surf,iters,'vac',opt_bulk_e,temp_print)
        vac_ls.append(vac)
        iters+=1
        vac=int(vac+1)
    if iters>=5:
        if diff_primary>rela_tol or diff_second>rela_tol:
            parprint('WARNING: Max Vacuum Íiterations reached! System may not converged.')
            parprint('Computation Suspended!')
            sys.exit()
    vac=vac_ls[-2]    
    parprint('Simulation Results Output:')
    parprint('Element = {}'.format(element))
    parprint('Structure = {}'.format(struc))
    parprint('converged h = {}'.format(h))
    parprint('converged k = {}'.format(k))
    parprint('converged smearing width = {}'.format(sw))
    parprint('converged layer = {}'.format(layer))
    parprint('converged vacuum = {} Ang'.format(vac))
    parprint('computation time = {} s'.format(time_ls[-2]))
    parprint(time_ls)
    parprint(vac_ls)

def surf_e_calc(pre,post,opt_bulk_e):
    pre_area=2*(pre.cell[0][0]*pre.cell[1][1])
    post_area=2*(post.cell[0][0]*post.cell[1][1])
    pre_e=pre.get_potential_energy()
    post_e=post.get_potential_energy()
    pre_num=float(re.findall(r'\d+',str(pre.symbols))[0])
    post_num=float(re.findall(r'\d+',str(post.symbols))[0])
    pre_surf_e=(1/pre_area)*(pre_e-pre_num*opt_bulk_e)
    post_surf_e=(1/post_area)*(post_e-post_num*opt_bulk_e)
    diff_surf_e=abs(post_surf_e-pre_surf_e)
    return diff_surf_e

# def surf_e_converge_calc(fst,snd,trd,opt_bulk_e):
#     fst_area=2*(fst.cell[0][0]*fst.cell[1][1])
#     snd_area=2*(snd.cell[0][0]*snd.cell[1][1])
#     trd_area=2*(trd.cell[0][0]*trd.cell[1][1])
#     fst_e=fst.get_potential_energy()
#     snd_e=snd.get_potential_energy()
#     trd_e=trd.get_potential_energy()
#     fst_num=float(re.findall(r'\d+',str(fst.symbols))[0])
#     snd_num=float(re.findall(r'\d+',str(snd.symbols))[0])
#     trd_num=float(re.findall(r'\d+',str(trd.symbols))[0])
#     fst_surf_e=(1/fst_area)*(fst_e-fst_num*opt_bulk_e)
#     snd_surf_e=(1/snd_area)*(snd_e-snd_num*opt_bulk_e)
#     trd_surf_e=(1/trd_area)*(trd_e-trd_num*opt_bulk_e)
#     diff_primary=max(abs(snd_surf_e-fst_surf_e),
#                     abs(trd_surf_e-fst_surf_e))
#     diff_second=abs(trd_surf_e-snd_surf_e)
#     return diff_primary, diff_second

def temp_output_printer(db,iters,key,opt_bulk_e,option=False):
    fst_r=db.get(iters-1)
    snd_r=db.get(iters)
    trd_r=db.get(iters+1)
    if option==True:
        parprint(key)
        parprint('2nd({})-1st({})'.format(snd_r[key],fst_r[key]),
                '=',
                np.round(surf_e_calc(db.get_atoms(iters),db.get_atoms(iters-1),opt_bulk_e),decimals=5))
        parprint('3rd({})-1st({})'.format(trd_r[key],fst_r[key]),
                '=',
                np.round(surf_e_calc(db.get_atoms(iters+1),db.get_atoms(iters-1),opt_bulk_e),decimals=5))
        parprint('3rd({})-2nd({})'.format(trd_r[key],snd_r[key]),
                '=',
                np.round(surf_e_calc(db.get_atoms(iters+1),db.get_atoms(iters),opt_bulk_e),decimals=5))