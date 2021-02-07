from gpaw import GPAW
from ase.build import bulk
from ase.db import connect
import os
import optimizer as opt
from ase.parallel import parprint
import numpy as np
import sys
from ase.io import read, write
from ase.parallel import paropen, parprint, world
from ase.calculators.calculator import kptdensity2monkhorstpack as kdens2mp
from gpaw import Mixer
from gpaw import Davidson

def bulk_auto_conv(element,
                    h=0.16,
                    k_density=4,
                    xc='PBE',
                    sw=0.1,
                    init_magmom=0,
                    maxiter=333,
                    spinpol=False,
                    rela_tol=10*10**(-3),
                    temp_print=True,
                    beta=0.05,
                    nmaxold=5,
                    weight=50.0):
    rep_location=(element+'/'+'bulk'+'/'+'results_report.txt')
    #initialize the kpts from the k_density
    orig_atom=bulk_builder(element)
    kpts=kdens2mp(orig_atom,kptdensity=k_density,even=True)
    if world.rank==0 and os.path.isfile(rep_location):
        os.remove(rep_location)
    with paropen(rep_location,'a') as f:
        parprint('Initial Parameters:',file=f)
        parprint('\t'+'Materials: '+element,file=f)
        parprint('\t'+'Lattice constants: '+str(np.round(orig_atom.get_cell_lengths_and_angles()[:3],decimals=5))+'Ang',file=f)    
        parprint('\t'+'Lattice angles: '+str(np.round(orig_atom.get_cell_lengths_and_angles()[3:],decimals=5))+'Degree',file=f)
        parprint('\t'+'xc: '+xc,file=f)
        parprint('\t'+'h: '+str(h),file=f)
        parprint('\t'+'k_density: '+str(k_density),file=f)
        parprint('\t'+'kpts: '+str(kpts),file=f)
        parprint('\t'+'sw: '+str(sw),file=f)
        parprint('\t'+'magmom: '+str(init_magmom),file=f)
        parprint('\t'+'spin polarized: '+str(spinpol),file=f)
        parprint('\t'+'rela_tol: '+str(rela_tol)+'eV',file=f)
    f.close()
    #connecting to databse
    db_h=connect(element+"/"+'bulk'+'/'+'grid_converge.db')
    db_k=connect(element+"/"+'bulk'+'/'+'kpts_converge.db')
    db_sw=connect(element+"/"+'bulk'+'/'+'sw_converge.db')
    db_final=connect('final_database'+'/'+'bulk.db')
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
        for j in range(1,grid_iters):
            h_ls.append(db_h.get(j).h)
    #start with grid spacing convergence
    while (diff_primary>rela_tol or diff_second>rela_tol) and grid_iters <= 6:
        atoms=bulk_builder(element)
        atoms.set_initial_magnetic_moments(init_magmom*np.ones(len(atoms)))
        calc=GPAW(xc=xc,
                    h=h,
                    kpts=kpts,
                    spinpol=spinpol,
                    maxiter=maxiter,
                    mixer=Mixer(beta,nmaxold,weight),
                    eigensolver=Davidson(3),
                    occupations={'name':'fermi-dirac','width':sw})
        atoms.set_calculator(calc)
        opt.optimize_bulk(atoms,step=0.05,fmax=0.01,location=element+"/"+'bulk'+'/'+'results_h',extname='{}'.format(h))
        db_h.write(atoms,h=h)
        if grid_iters>=2:
            fst=db_h.get_atoms(id=grid_iters-1)
            snd=db_h.get_atoms(id=grid_iters)
            trd=db_h.get_atoms(id=grid_iters+1)
            diff_primary=max(abs(snd.get_potential_energy()-fst.get_potential_energy()),
                            abs(trd.get_potential_energy()-fst.get_potential_energy()))
            diff_second=abs(trd.get_potential_energy()-snd.get_potential_energy())
            if temp_print == True:
                temp_output_printer(db_h,grid_iters,'h',rep_location)
        h_ls.append(h)
        h=np.round(h-0.02,decimals=2)
        grid_iters+=1
    if grid_iters>=6:
        if diff_primary>rela_tol or diff_second>rela_tol:
            with paropen(rep_location,'a') as f:
                parprint("WARNING: Max GRID iterations reached! System may not be converged.",file=f)
                parprint("Computation Suspended!",file=f)
            f.close()
            sys.exit()
    h=h_ls[-3]
    #kpts convergence
    diff_primary=100
    diff_second=100
    k_iters=len(db_k)+1
    k_ls=[kpts]
    if k_iters>=2:
        for i in range(2,k_iters):
            fst=db_k.get_atoms(id=i-1)
            snd=db_k.get_atoms(id=i)
            trd=db_k.get_atoms(id=i+1)
            diff_primary=max(abs(snd.get_potential_energy()-fst.get_potential_energy()),
                            abs(trd.get_potential_energy()-fst.get_potential_energy()))
            diff_second=abs(trd.get_potential_energy()-snd.get_potential_energy())
            if temp_print == True:
                temp_output_printer(db_k,i,'kpts',rep_location)
    if k_iters>1:
        for j in range(1,k_iters):
            k_ls.append(db_k.get(j).kpts)
    else:
        k_density=mp2kdens(db_h.get_atoms(len(db_h)-2),kpts) ##Need to improve this in the future (kpts to density)
        db_k.write(db_h.get_atoms(len(db_h)-2),k_density=','.join(map(str, k_density)),kpts=','.join(map(str, kpts)))
    while (diff_primary>rela_tol or diff_second>rela_tol) and k_iters <= 6: 
        kpts=kpts+2
        atoms=bulk_builder(element)
        atoms.set_initial_magnetic_moments(init_magmom*np.ones(len(atoms)))
        calc=GPAW(xc=xc,
                    h=h,
                    kpts=kpts,
                    spinpol=spinpol,
                    maxiter=maxiter,
                    mixer=Mixer(beta,nmaxold,weight),
                    eigensolver=Davidson(3),
                    occupations={'name':'fermi-dirac','width':sw})
        atoms.set_calculator(calc)
        opt.optimize_bulk(atoms,step=0.05,fmax=0.01,location=element+"/"+'bulk'+'/'+'results_k',extname='{}'.format(kpts[0]))
        k_density=mp2kdens(atoms,kpts)
        db_k.write(atoms,k_density=','.join(map(str, k_density)),kpts=','.join(map(str, kpts)))
        if k_iters>=2:
            fst=db_k.get_atoms(id=k_iters-1)
            snd=db_k.get_atoms(id=k_iters)
            trd=db_k.get_atoms(id=k_iters+1)
            diff_primary=max(abs(snd.get_potential_energy()-fst.get_potential_energy()),
                            abs(trd.get_potential_energy()-fst.get_potential_energy()))
            diff_second=abs(trd.get_potential_energy()-snd.get_potential_energy())
            if temp_print == True:
                temp_output_printer(db_k,k_iters,'kpts',rep_location)
        k_iters+=1
        k_ls.append(kpts)
    if k_iters>=6:
        if diff_primary>rela_tol or diff_second>rela_tol:
            with paropen(rep_location,'a') as f:
                parprint("WARNING: Max K_DENSITY iterations reached! System may not be converged.",file=f)
                parprint("Computation Suspended!",file=f)
            f.close()
            sys.exit()
    kpts=k_ls[-3]
    #smearing-width convergence test
    diff_primary=100
    diff_second=100
    sw_iters=1
    sw_ls=[sw]
    db_sw.write(db_k.get_atoms(len(db_k)-2),sw=sw)
    while (diff_primary>rela_tol or diff_second>rela_tol) and sw_iters <= 6: 
        sw=sw/2
        atoms=bulk_builder(element)
        atoms.set_initial_magnetic_moments(init_magmom*np.ones(len(atoms)))
        calc=GPAW(xc=xc,
                    h=h,
                    kpts=kpts,
                    spinpol=spinpol,
                    maxiter=maxiter,
                    mixer=Mixer(beta,nmaxold,weight),
                    eigensolver=Davidson(3),
                    occupations={'name':'fermi-dirac','width':sw})
        atoms.set_calculator(calc)
        opt.optimize_bulk(atoms,step=0.05,fmax=0.01,location=element+"/"+'bulk'+'/'+'results_sw',extname='{}'.format(sw))
        db_sw.write(atoms,sw=sw)
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
        sw_ls.append(sw)
    if sw_iters>=6:
        if diff_primary>rela_tol or diff_second>rela_tol:
            with paropen(rep_location,'a') as f:
                parprint("WARNING: Max SMEARING-WIDTH iterations reached! System may not be converged.",file=f)
                parprint("Computation Suspended!",file=f)
            f.close()
            sys.exit()
    sw=sw_ls[-3]
    final_atom=db_sw.get_atoms(id=len(db_sw)-2)
    k_density=mp2kdens(final_atom,kpts)[0]
    init_magmom=final_atom.get_magnetic_moments()
    #writing final_atom to final_db
    id=db_final.reserve(name=element)
    if id is None:
        id=db_final.get(name=element).id
        db_final.update(id=id,atoms=final_atom,h=h,k_density=k_density,sw=sw,name=element,xc=xc,kpts=','.join(map(str, kpts)),spin=spinpol)
    else:
        db_final.write(final_atom,id=id,name=element,h=h,k_density=k_density,sw=sw,xc=xc,kpts=','.join(map(str, kpts)),spin=spinpol)
    with paropen(rep_location,'a') as f:
        parprint('Final Parameters:',file=f)
        parprint('\t'+'h: '+str(h),file=f)
        parprint('\t'+'k_density: '+str(k_density),file=f)
        parprint('\t'+'kpts: '+str(kpts),file=f)
        parprint('\t'+'sw: '+str(sw),file=f)
        parprint('\t'+'magmom: '+str(init_magmom),file=f)
        parprint('Final Output: ',file=f)
        parprint('\t'+'Lattice constants: '+str(np.round(final_atom.get_cell_lengths_and_angles()[:3],decimals=5))+'Ang',file=f)    
        parprint('\t'+'Lattice angles: '+str(np.round(final_atom.get_cell_lengths_and_angles()[3:],decimals=5))+'Degree',file=f)    
        parprint('\t'+'pot_e: '+str(np.round(final_atom.get_potential_energy(),decimals=5))+'eV',file=f)
    f.close()


def bulk_builder(element):
    location='orig_cif_data'+'/'+element+'.cif'
    atoms=read(location)
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