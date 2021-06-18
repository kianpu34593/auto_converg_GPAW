from gpaw import GPAW,Mixer,Davidson
from ase.build import bulk
from ase.db import connect
import os
import GPAW_converge.molecule.optimizer as opt
from gpaw.eigensolvers import RMMDIIS
from ase.parallel import parprint
import numpy as np
import sys
from ase.io import read, write
from ase.parallel import paropen, parprint, world
from ase.calculators.calculator import kptdensity2monkhorstpack as kdens2mp

def homo_lumo(element,gpaw_calc,relax_xc,
                    init_magmom=0,sub_dir=None):
    calc_dict=gpaw_calc.__dict__['parameters']
    xc=calc_dict['xc']
    if sub_dir is None:
        sub_dir = xc
    cid=element.split('_')[-2:]
    cid='_'.join(cid)
    rep_location=cid+'/'+'HOLO_'+sub_dir+'_results_report.txt'
    if world.rank==0 and os.path.isfile(rep_location):
        os.remove(rep_location)
    with paropen(rep_location,'a') as f:
        parprint('Parameters:',file=f)
        parprint('\t'+'Materials: '+element,file=f)
        parprint('\t'+'xc: '+xc.split('-')[0],file=f)
        parprint('\t'+'h: '+str(calc_dict['h']),file=f)
        parprint('\t'+'kpts: '+str(calc_dict['kpts']),file=f)
        parprint('\t'+'sw: '+str(calc_dict['occupations']),file=f)
        parprint('\t'+'spin polarized: '+str(calc_dict['spinpol']),file=f)
        if calc_dict['spinpol']:
            parprint('\t'+'magmom: '+str(init_magmom),file=f)
    f.close()
    #connecting to databse
    db_opt=connect('final_database'+'/'+'bulk_'+relax_xc+'.db')
    db_holo=connect('final_database'+'/'+'HOLO_'+sub_dir+'.db')
    atoms=db_opt.get_atoms(name=element)
    atoms.set_calculator(gpaw_calc)
    #(atoms,cid,XC,fmax=solver_fmax, maxstep=solver_maxstep, replay_traj=None)
    opt.SPE_calc(atoms,name=cid+'/'+'homo-lumo'+'/'+sub_dir.split('-')[0])
    (homo,lumo)=gpaw_calc.get_homo_lumo()
    id=db_holo.reserve(name=element)
    if id is None:
        id=db_holo.get(name=element).id
        db_holo.update(id=id,atoms=atoms,name=element,homo=homo,lumo=lumo,
                        h=calc_dict['h'],sw=calc_dict['occupations']['width'],xc=calc_dict['xc'],spin=calc_dict['spinpol'],
                        kpts=str(','.join(map(str, calc_dict['kpts']))))
    else:
        db_holo.write(atoms,id=id,name=element,homo=homo,lumo=lumo,
                        h=calc_dict['h'],sw=calc_dict['occupations']['width'],xc=calc_dict['xc'],spin=calc_dict['spinpol'],
                        kpts=str(','.join(map(str, calc_dict['kpts']))))