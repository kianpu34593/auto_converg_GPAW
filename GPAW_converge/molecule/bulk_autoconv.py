from gpaw import GPAW,Mixer,Davidson
from ase.build import bulk
from ase.db import connect
import os
import GPAW_converge.molecule.optimizer as opt
from ase.parallel import parprint
import numpy as np
import sys
from ase.io import read, write
from ase.parallel import paropen, parprint, world
from ase.calculators.calculator import kptdensity2monkhorstpack as kdens2mp

def bulk_auto_conv(element,gpaw_calc,
                    parameters=['h','k','sw'],
                    rela_tol=10*10**(-3),
                    init_magmom=0,
                    temp_print=True,
                    solver_fmax=0.01,
                    solver_maxstep=0.04):
    calc_dict=gpaw_calc.__dict__['parameters']
    cid=element.split('_')[-1]
    orig_atom=bulk_builder(element)
    XC=calc_dict['xc'].split('-')[0]
    rep_location=(cid+'/'+XC+'/'+'results_report.txt')
    if world.rank==0 and os.path.isfile(rep_location):
        os.remove(rep_location)
    with paropen(rep_location,'a') as f:
        parprint('Initial Parameters:',file=f)
        parprint('\t'+'Materials: '+element,file=f)
        parprint('\t'+'Lattice constants: '+str(np.round(orig_atom.get_cell_lengths_and_angles()[:3],decimals=5))+'Ang',file=f)    
        parprint('\t'+'Lattice angles: '+str(np.round(orig_atom.get_cell_lengths_and_angles()[3:],decimals=5))+'Degree',file=f)
        parprint('\t'+'xc: '+XC,file=f)
        parprint('\t'+'h: '+str(calc_dict['h']),file=f)
        parprint('\t'+'kpts: '+str(calc_dict['kpts']),file=f)
        parprint('\t'+'sw: '+str(calc_dict['occupations']),file=f)
        parprint('\t'+'spin polarized: '+str(calc_dict['spinpol']),file=f)
        if calc_dict['spinpol']:
            parprint('\t'+'magmom: '+str(init_magmom),file=f)
        parprint('\t'+'rela_tol: '+str(rela_tol)+'eV',file=f)
        parprint('Optimizing Parameters: '+str(parameters),file=f)
    f.close()
    #connecting to databse
    db_final=connect('final_database'+'/'+'bulk_'+calc_dict['xc']+'.db')
    if 'h' in parameters:
        db_h=connect(cid+'/'+calc_dict['xc'].split('-')[0]+'/'+'grid_converge.db')
        diff_primary=100
        diff_second=100
        grid_iters=len(db_h)
        h_ls=[]
        if grid_iters>=2:
            for i in range(2,grid_iters):
                fst=db_h.get_atoms(id=i-1)
                snd=db_h.get_atoms(id=i)
                trd=db_h.get_atoms(id=i+1)
                diff_primary=max(abs(snd.get_potential_energy()-fst.get_potential_energy()),
                                abs(trd.get_potential_energy()-fst.get_potential_energy()))
                diff_second=abs(trd.get_potential_energy()-snd.get_potential_energy())
                if temp_print == True:
                    temp_output_printer(db_h,i,'h',rep_location)
        if grid_iters>0:
            for j in range(1,grid_iters+1):
                h_ls.append(db_h.get(j).h)
        #start with grid spacing convergence
        while (diff_primary>rela_tol or diff_second>rela_tol) and grid_iters <= 6:
            atoms=bulk_builder(element)
            if calc_dict['spinpol']:
                atoms.set_initial_magnetic_moments(init_magmom*np.ones(len(atoms)))
            atoms.set_calculator(gpaw_calc)
            opt.relax(atoms,cid,'h',calc_dict['h'],XC,fmax=solver_fmax, maxstep=solver_maxstep, replay_traj=None)
            db_h.write(atoms,h=calc_dict['h'])
            if grid_iters>=2:
                fst=db_h.get_atoms(id=grid_iters-1)
                snd=db_h.get_atoms(id=grid_iters)
                trd=db_h.get_atoms(id=grid_iters+1)
                diff_primary=max(abs(snd.get_potential_energy()-fst.get_potential_energy()),
                                abs(trd.get_potential_energy()-fst.get_potential_energy()))
                diff_second=abs(trd.get_potential_energy()-snd.get_potential_energy())
                if temp_print == True:
                    temp_output_printer(db_h,grid_iters,'h',rep_location)
            h_ls.append(calc_dict['h'])
            gpaw_calc.__dict__['parameters']['h']=np.round(calc_dict['h']-0.02,decimals=2)
            calc_dict=gpaw_calc.__dict__['parameters']
            grid_iters+=1
        if grid_iters>=6:
            if diff_primary>rela_tol or diff_second>rela_tol:
                with paropen(rep_location,'a') as f:
                    parprint("WARNING: Max GRID iterations reached! System may not be converged.",file=f)
                    parprint("Computation Suspended!",file=f)
                f.close()
                sys.exit()
        h=h_ls[-3]
        gpaw_calc.__dict__['parameters']['h']=h
        calc_dict=gpaw_calc.__dict__['parameters']
    #kpts convergence
    # elif 'k' in parameters:
    #     db_k=connect(element+"/"+'bulk'+'/'+'kpts_converge.db')
    #     diff_primary=100
    #     diff_second=100
    #     k_iters=len(db_k)+1
    #     k_ls=[calc_dict['kpts']]
    #     k_density=mp2kdens(db_h.get_atoms(len(db_h)-2),calc_dict['kpts'])
    #     db_k.write(db_h.get_atoms(len(db_h)-2),k_density=','.join(map(str, k_density)),kpts=str(','.join(map(str, calc_dict['kpts']))))
    #     while (diff_primary>rela_tol or diff_second>rela_tol) and k_iters <= 6: 
    #         atoms=bulk_builder(element)
    #         kpts=[int(i+2) for i in calc_dict['kpts']]
    #         k_density=mp2kdens(atoms,kpts)
    #         gpaw_calc.__dict__['parameters']['kpts']=kpts
    #         calc_dict=gpaw_calc.__dict__['parameters']
    #         # atoms=bulk_builder(element)
    #         if calc_dict['spinpol']:
    #             atoms.set_initial_magnetic_moments(init_magmom*np.ones(len(atoms)))
    #         atoms.set_calculator(gpaw_calc)
    #         opt.relax(atoms,cid,'k',calc_dict['k'],fmax=0.01, maxstep=0.04, replay_traj=None)
    #     db_k.write(atoms,k_density=','.join(map(str, k_density)),kpts=str(','.join(map(str, calc_dict['kpts']))))
    #     if k_iters>=2:
    #         fst=db_k.get_atoms(id=k_iters-1)
    #         snd=db_k.get_atoms(id=k_iters)
    #         trd=db_k.get_atoms(id=k_iters+1)
    #         diff_primary=max(abs(snd.get_potential_energy()-fst.get_potential_energy()),
    #                         abs(trd.get_potential_energy()-fst.get_potential_energy()))
    #         diff_second=abs(trd.get_potential_energy()-snd.get_potential_energy())
    #         if temp_print == True:
    #             temp_output_printer(db_k,k_iters,'kpts',rep_location)
    #     k_iters+=1
    #     k_ls.append(kpts)
    # if k_iters>=6:
    #     if diff_primary>rela_tol or diff_second>rela_tol:
    #         with paropen(rep_location,'a') as f:
    #             parprint("WARNING: Max K_DENSITY iterations reached! System may not be converged.",file=f)
    #             parprint("Computation Suspended!",file=f)
    #         f.close()
    #         sys.exit()
    # kpts=k_ls[-3]
    # gpaw_calc.__dict__['parameters']['kpts']=kpts
    # calc_dict=gpaw_calc.__dict__['parameters']
    #smearing-width convergence test
    if 'sw' in parameters:
        db_sw=connect(cid+'/'+calc_dict['xc'].split('-')[0]+'/'+'sw_converge.db')
        diff_primary=100
        diff_second=100
        sw_iters=1
        sw_ls=[calc_dict['occupations']['width']]
        db_sw.write(db_h.get_atoms(len(db_h)-2),sw=calc_dict['occupations']['width'])
        while (diff_primary>rela_tol or diff_second>rela_tol) and sw_iters <= 6: 
            atoms=bulk_builder(element)
            gpaw_calc.__dict__['parameters']['occupations']['width']=calc_dict['occupations']['width']/2
            calc_dict=gpaw_calc.__dict__['parameters']
            if calc_dict['spinpol']:
                atoms.set_initial_magnetic_moments(init_magmom*np.ones(len(atoms)))
            atoms.set_calculator(gpaw_calc)
            opt.relax(atoms,cid,'sw',calc_dict['occupations']['width'],XC,fmax=solver_fmax, maxstep=solver_maxstep, replay_traj=None)
            db_sw.write(atoms,sw=calc_dict['occupations']['width'])
            if sw_iters>=2:
                fst=db_sw.get_atoms(id=sw_iters-1)
                snd=db_sw.get_atoms(id=sw_iters)
                trd=db_sw.get_atoms(id=sw_iters+1)
                diff_primary=max(abs(snd.get_potential_energy()-fst.get_potential_energy()),
                            abs(trd.get_potential_energy()-fst.get_potential_energy()))
                diff_second=abs(trd.get_potential_energy()-snd.get_potential_energy())
                if temp_print == True:
                    temp_output_printer(db_sw,sw_iters,'sw',rep_location)
            sw_iters+=1
            sw_ls.append(calc_dict['occupations']['width'])
        if sw_iters>=6:
            if diff_primary>rela_tol or diff_second>rela_tol:
                with paropen(rep_location,'a') as f:
                    parprint("WARNING: Max SMEARING-WIDTH iterations reached! System may not be converged.",file=f)
                    parprint("Computation Suspended!",file=f)
                f.close()
                sys.exit()
        sw=sw_ls[-3]
        gpaw_calc.__dict__['parameters']['occupations']['width']=sw
        calc_dict=gpaw_calc.__dict__['parameters']
    final_atom=db_sw.get_atoms(id=len(db_sw)-2)
    #k_density=mp2kdens(final_atom,calc_dict['kpts'])[0]
    #writing final_atom to final_db
    id=db_final.reserve(name=element)
    if id is None:
        id=db_final.get(name=element).id
        db_final.update(id=id,atoms=final_atom,name=element,
                        h=calc_dict['h'],sw=calc_dict['occupations']['width'],xc=calc_dict['xc'],spin=calc_dict['spinpol'],
                        kpts=str(','.join(map(str, calc_dict['kpts']))))
    else:
        db_final.write(final_atom,id=id,name=element,
                        h=calc_dict['h'],sw=calc_dict['occupations']['width'],xc=calc_dict['xc'],spin=calc_dict['spinpol'],
                        kpts=str(','.join(map(str, calc_dict['kpts']))))
    with paropen(rep_location,'a') as f:
        parprint('Final Parameters:',file=f)
        parprint('\t'+'h: '+str(calc_dict['h']),file=f)
        parprint('\t'+'kpts: '+str(calc_dict['kpts']),file=f)
        parprint('\t'+'sw: '+str(calc_dict['occupations']['width']),file=f)
    f.close()


def bulk_builder(element):
    location='input_xyz'+'/'+element+'.xyz'
    atoms=read(location)
    pos = atoms.get_positions()
    xl = max(pos[:,0])-min(pos[:,0])+15
    yl = max(pos[:,1])-min(pos[:,1])+15
    zl = max(pos[:,2])-min(pos[:,2])+15
    maxlength=max([xl,yl,zl])
    atoms.set_cell((maxlength,maxlength,maxlength))
    atoms.center()
    atoms.set_pbc([False,False,False])
    return atoms

def temp_output_printer(db,iters,key,location):
    fst_r=db.get(iters-1)
    snd_r=db.get(iters)
    trd_r=db.get(iters+1)
    with paropen(location,'a') as f:
        parprint('Optimizing parameter: '+key,file=f)
        parprint('\t'+'1st: '+str(fst_r[key])+' 2nd: '+str(snd_r[key])+' 3rd: '+str(trd_r[key]),file=f)
        parprint('\t'+'2nd-1st: '+str(np.round(abs(snd_r['energy']-fst_r['energy']),decimals=5))+'eV',file=f)
        parprint('\t'+'3rd-1st: '+str(np.round(abs(trd_r['energy']-fst_r['energy']),decimals=5))+'eV',file=f)
        parprint('\t'+'3rd-2nd: '+str(np.round(abs(trd_r['energy']-snd_r['energy']),decimals=5))+'eV',file=f)
    f.close()

def mp2kdens(atoms,kpts):
    recipcell=atoms.get_reciprocal_cell()
    kptdensity_ls=[]
    for i in range(len(kpts)):
        kptdensity = kpts[i]/(2 * np.pi * np.sqrt((recipcell[i]**2).sum()))
        kptdensity_ls.append(np.round(kptdensity,decimals=4))
    return kptdensity_ls