$Title One node Optimal Technology Mix for VRE integration

$call echo "%gams.input%" | sed -e "s/.*\\\([^\\]*\)\\[^\\]*/$setglobal FNAME \1/" > blub
$include blub
$call rm blub

$OnText

This model determines optimal technology mix, including wind, solar PV, and
energy storage, to achieve a given VRE target.

$OffText

$setGlobal sim_year         2030
$setGlobal NumberOfPeriods  8760
$setGlobal OutageDur        24
$setGlobal ResilienceOption 1
$setGlobal DemandCharges    0
$setGlobal indir            Data
$setGlobal outdir           Outputs
$setGlobal case_name        Checks

$call mkdir "%outdir%" > nul 2> nul

Set h hours in the analysis period /1*%NumberOfPeriods%/

    h_step1(h) hours in the analysis period /1*%OutageDur%/
    
    m months /1*12/

Alias (h, hh, hhh)


Set    bu Balancing units(dispatchable power plants) 
/
$include %indir%\%case_name%\Set_bu(BalancingUnits).txt
/

Set    k potential solar PV plants
/
$include %indir%\%case_name%\Set_k_SolarPV.csv   
/

Set    w potential wind plants
/
$include %indir%\%case_name%\Set_w_Wind.csv
/

Set    l properties of power plants
/
$include %indir%\%case_name%\Set_l_Properties.csv
/


Set j energy storage technologies
/
$include %indir%\%case_name%\Set_j_StorageTechs.csv
/

Set b(j) storage technologies with coupled charging and discharging units
/
$include %indir%\%case_name%\Set_b(j)_CoupledStorageTech.csv
/

Set    sp properties of storage technologies
/
$include %indir%\%case_name%\Set_sp_StorTechProperties.csv
/
;

Set

hm(h,m)  /
          (1*744).1
          (745*1416).2
          (1417*2160).3
          (2161*2880).4
          (2881*3624).5
          (3625*4344).6
          (4345*5088).7
          (5089*5832).8
          (5833*6552).9
          (6553*7296).10
          (7297*8016).11
          (8017*8760).12

          /
;

Scalar
    begin_year   weekday index of Jan 1 2030 /1/  
* Jan 1 2030 is a Tuesday → W0 = 1
    begin_peak /7/
    end_peak /18/ ;
    

Set
    peak(h)   yes if hour h is weekday 7am–7pm;

Scalar
    day_idx, hour, week_idx;

Loop(h,
        day_idx    = floor(ord(h)-1)/24;
        hour = mod(ord(h),24);
        week_idx    = mod(begin_year + day_idx, begin_peak);
        peak(h) = no;
    If ( (week_idx <= 4) and (hour >= begin_peak) and (hour <= end_peak),
        peak(h) = yes;
        );
    );


Set

offpeak(h) off peak hours set ;

offpeak(h)$(not peak(h)) = yes ;

Set Runs runs for the analysis /1/


Scalars
         FCR_VRE Fixed Charge Rate for VRE 
         FCR_GasCC Fixed Charge Rate for Gas CC 
         GenMix_Target Renewables generation mix where 1 means all are renewables and 0 means none of the generation technologies are renewables
         GenMix_Target_step2 Renewables generation mix where 1 means all are renewables and 0 means none of the generation technologies are renewables
         CapexGasCC Capex for gas combined cycle units (US$ per kW) 
         HR Heat rate of gas combined cycle units (MMBtu per MWh) 
         GasPrice Gas prices (US$ per MMBtu per) 
         FOM_GasCC FO&M for gas combined cycle units (US$ per kW-year) 
         VOM_GasCC VO&M for gas combined cycle units (US$ per MWh) 
         AlphaNuclear Activation of nuclear generation 
         AlphaLargHy Activation of large hydro generation 
         AlphaOtheRe Activation of other renewable generation 
         MaxCycles Lifetime (100% DoD) of Li-Ion batteries (cycles) 
         r discount rate 
         LifeTimeVRE life time of the VRE in years
         LifeTimeGasCC life time of the gas engine in years
         CriticalLoadFrac Percentage of Critical Load Served     
         max_backup_power_dur maximum backup power storage duration in hours 
         outage_start_hour first hour of outage throughout the year
         SOC_restore_hours number of hours required for restoring the storage system
         critical_peak_load desired critical peak load for the design of back-up power (MW)
         pv_footprint unit pv footprint in acres
         wind_footprint unit wind footprint in acres
         total_available_footprint total available footprint in acres
;

$call CSV2GDX %indir%\%case_name%\Scalars.csv Output=%indir%\%case_name%\Scalars.gdx ID=ScalarInputs StoreZero = Y UseHeader=y Index=1 Values=(2..LastCol)
Parameter ScalarInputs(*)   scalars ;
$GDXIN %indir%\%case_name%\Scalars.gdx
$LOAD ScalarInputs
$GDXIN
;

AlphaNuclear     = ScalarInputs('AlphaNuclear');
AlphaLargHy      = ScalarInputs('AlphaLargHy');
AlphaOtheRe      = ScalarInputs('AlphaOtheRe');
r                = ScalarInputs('r');
FCR_VRE          = ScalarInputs('FCR_VRE');
FCR_GasCC        = ScalarInputs('FCR_GasCC');
LifeTimeVRE      = ScalarInputs('LifeTimeVRE');
LifeTimeGasCC    = ScalarInputs('LifeTimeGasCC');
max_backup_power_dur = ScalarInputs('max_backup_power_dur');
outage_start_hour = ScalarInputs('outage_start_hour');
SOC_restore_hours = ScalarInputs('SOC_restore_hours');
CriticalLoadFrac  = ScalarInputs('CriticalLoadFrac');
GenMix_Target     = ScalarInputs('GenMix_Target');
CapexGasCC        = ScalarInputs('CapexGasCC');
HR                = ScalarInputs('HR');
GasPrice          = ScalarInputs('GasPrice');
FOM_GasCC         = ScalarInputs('FOM_GasCC');
VOM_GasCC         = ScalarInputs('VOM_GasCC');
MaxCycles         = ScalarInputs('MaxCycles');
critical_peak_load = ScalarInputs('critical_peak_load');
pv_footprint      = ScalarInputs('pv_footprint');
wind_footprint    = ScalarInputs('wind_footprint');
total_available_footprint = ScalarInputs('total_available_footprint');
GenMix_Target_step2 = GenMix_Target ;

FCR_VRE = (r*(1+r)**LifeTimeVRE)/((1+r)**LifeTimeVRE-1);

FCR_GasCC = (r*(1+r)**LifeTimeGasCC)/((1+r)**LifeTimeGasCC-1);


Parameter Load(h) Load for every hour in the analysis period (MW)
/
$Ondelim
$include %indir%\%case_name%\Load_hourly_%sim_year%.csv
$Offdelim
/

Parameter critical_load(h) critical load time series (MW);
critical_load(h) = CriticalLoadFrac * Load(h);

If (critical_peak_load = 0,
    critical_peak_load = smax(h,critical_load(h)) ;
    );

Parameter Load_step2(h) ;

Load_step2(h) = Load(h) ;

Parameter BackupSOC(j) ; 


Parameter Nuclear(h) Generation from nuclear power plants for every hour in the analysis period (MW)
/
$Ondelim
$include %indir%\%case_name%\Nucl_hourly_%sim_year%.csv
$Offdelim
/

Parameter LargeHydro(h) Generation from large hydro power plants for every hour in the analysis period (MW)
/
$Ondelim
$include %indir%\%case_name%\lahy_hourly_%sim_year%.csv
$Offdelim
/

Parameter OtherRenewables(h) Generation from other renewable power plants for every hour in the analysis period (MW)
/
$Ondelim
$include %indir%\%case_name%\otre_hourly_%sim_year%.csv
$Offdelim
/
;

Parameter fixed_dem_rate(h) fixed demand charges in $ per MW

/
$Ondelim
$include %indir%\%case_name%\fixed_dem_charges.csv
$Offdelim
/
;

Parameter variable_dem_rate(h) variable demand charges in $ per MW

/
$Ondelim
$include %indir%\%case_name%\var_dem_charges.csv
$Offdelim
/
;

Parameter ImportCap(h) Max import power (MW)
/
$Ondelim
$include %indir%\%case_name%\Import_Cap_%sim_year%.csv
$Offdelim
/;

*ImportCap(h) = 0 ; 

Parameter ExportCap(h) Max export power (MW)
/
$Ondelim
$include %indir%\%case_name%\Export_Cap_%sim_year%.csv
$Offdelim
/
;

ExportCap(h) = 0 ; 


Parameter ImportPrices(h) Prices for power imports ($ per MWh)
/
$Ondelim
$include %indir%\%case_name%\Import_Prices_%sim_year%.csv
$Offdelim
/

Parameter ExportPrices(h) Prices for power exports ($ per MWh)
/
$Ondelim
$include %indir%\%case_name%\Export_Prices_%sim_year%.csv
$Offdelim
/
;

*ImportPrices(h) = 0*ImportPrices(h) ;
ExportPrices(h) = 0*ExportPrices(h) ;

Parameter LargeHydroBudget(h) Generation from large hydro power plants for every hour in the analysis period (MW)
/
$Ondelim
$include %indir%\%case_name%\lahy_hourly_%sim_year%.csv
$Offdelim
/

Table CFSolar(h,k) Hourly capacity factor for solar PV plants (fraction)
$Ondelim
$include %indir%\%case_name%\CFSolar_%sim_year%.csv
$Offdelim

Table CFWind(h,w) Hourly capacity factor for wind plants (fraction)
$Ondelim
$include %indir%\%case_name%\CFWind_%sim_year%.csv
$Offdelim

Table CapSolar(k,l) Properties of the solar PV plants
$Ondelim
$include %indir%\%case_name%\CapSolar_%sim_year%.csv
$Offdelim

Table CapWind(w,l) Properties of the wind plants
$Ondelim
$include %indir%\%case_name%\CapWind_%sim_year%.csv
$Offdelim

Table StorageData(sp,j) Properties of storage technologies
$Ondelim
$include %indir%\%case_name%\StorageData_%sim_year%.csv
$Offdelim
;

Table DataBU(bu,*) Properties of the balancing units
$Ondelim
$include %indir%\%case_name%\Data_Balancing_Units_%sim_year%.csv
$Offdelim


Parameter CRF(j) Capital recovery factor for storage technology j
Parameter CRF_GasCC(bu) Capital recovery factor for balancing unit bu
;

CRF(j) = (r*(1+r)**StorageData('Lifetime',j))/((1+r)**StorageData('Lifetime',j)-1);
CRF_GasCC(bu) = (r*(1+r)**DataBU(bu,'LifeTime'))/((1+r)**DataBU(bu,'LifeTime')-1);

Free variable
         TSC Total electricity supply cost

Positive Variables
         PC(j,h) Charging power for storage technology j during hour h
         PD(j,h) Discharging power for storage technology j during hour h
         SOC(j,h) State-of-charge (SOC) for storage technology j during hour h
         Pcha(j) Charge power capacity for storage technology j
         Pdis(j) Discharge power capacity for storage technology j
         Ecap(j) Energy capacity for storage technology j


         GenPV(h) Generated solar PV power during hour h
         CurtPV(h) Generated solar PV power during hour h
         GenWind(h) Generated wind power during hour h
         CurtWind(h) Generated wind power during hour h
         CapCC(bu) Capacity requirements for backup gas combined cycle units (MW)
         GenCC(h,bu) Generation from backup gas combined cycle units (MWh)
         Ypv(k) Capacity selection for solar PV plant k
         Ywind(w) Capacity selection for wind plant w
         
         Imports(h) power imports (MWh)
         Exports(h) power exports (MWh)
         
         Fixed_dem_charge(m) Fiexed demand charges ($)
         Peak_variable_dem_charge(m) Peak variable demand charges ($)
         Offpeak_variable_dem_charge(m) Off-peak variable demand charges ($)
;

Ypv.up(k)   = 1;
Ywind.up(w) = 1;
Ypv.fx(k)   = 1;
Ywind.fx(w) = 1;

Imports.up(h) = ImportCap(h);
Exports.up(h) = ExportCap(h);
*Imports.up(h) = max (0, Load(h)-sum(k,CFSolar(h,k)*CapSolar(k,'capacity'))-sum(w, CFWind(h,w)*CapWind(w,'capacity'))- AlphaNuclear*Nuclear(h)-AlphaLargHy*LargeHydroBudget(h)-AlphaOtheRe*OtherRenewables(h));
*Imports.up(h) = max (0, Load(h)-sum(k,CFSolar(h,k)*CapSolar(k,'capacity'))-sum(w, CFWind(h,w)*CapWind(w,'capacity'))- AlphaNuclear*Nuclear(h)-AlphaLargHy*LargeHydroBudget(h)-AlphaOtheRe*OtherRenewables(h));

ExportCap(h)= 1.0*ExportCap(h);


Binary variables
         Ystorage(j,h) 1 if storage technology j is charging during hour h (0 otherwise)

;

Equations
         ObjDes objective function
         Obj objective function
         Supply Electricity supply during hour h
         GenMix_Share Equation for VRE target
         SolarBal Balance of availability of solar PV power during hour h
         WindBal Balance of availability of wind power during hour h
         Footprint Footprint for renewables available

         HydroBudget
         ChargSt Constraint for charging the storage devices
         DischargSt Constraint for discharging the storage devices
         MaxPC Maximum charging power for storage technology j during hour h
         MaxPD Maximum discharging power for storage technology j during hour h
         MaxSOC Maximum SOC for storage technology j during hour h
         SOCBal SOC balance storage technology j during hour h > 1
         IniBal Initial (h = 1) SOC balance for storage technology j
         MaxPcha Maximum charge power capacity for storage technology j
         MaxPdis Maximum discharge power capacity for storage technology j
         PchaPdis Coupling of charge and discharge power capacity for battery technology b
         PchaPdisDes
         MinEcap Minimum energy capacity for storage technology j
         MaxEcap Maximum energy capacity for storage technology j
         BackupGen Required capacity from backup combined cycle units
         MaxCycleYear Maximum number of cycles per year for Li-Ion batteries
         
         SupplyDes Electricity supply during hour h in the design stage for resilience design
         GenMix_ShareDes Equation for VRE target in the design stage for resilience design
         SolarBalDes Balance of availability of solar PV power during hour h the design stage for resilience design
         WindBalDes Balance of availability of wind power during hour h the design stage for resilience design
         HydroBudgetDes
         ChargStDes Constraint for charging the storage devices the design stage for resilience design
         DischargStDes  Constraint for discharging the storage devices the design for resilience design
         MaxPCDes Maximum charging power for storage technology j during hour h the design for resilience design
         MaxPDDes Maximum discharging power for storage technology j during hour h the design for resilience design
         MaxSOCDes Maximum SOC for storage technology j during hour h the design for resilience design
         SOCBalDes SOC balance storage technology j during hour h > 1 the design for resilience design
         BackupGenDes Required capacity from backup combined cycle units the design for resilience design

         BackupEnergyOutage State of charge requirement to be kept in hours outside of outages
         
         Fixed_demand_charge Fixed monthly demand charges 
         Peak_variable_demand_charge Variable monthly demand charges corresponding to peak hours
         Offpeak_variable_demand_charge Variable monthly demand charges corresponding to offpeak hours

;
                 
Obj..    TSC =e= sum(k, (FCR_VRE*(1000*CapSolar(k,'CAPEX_M') + CapSolar(k,'trans_cap_cost')) + 1000*CapSolar(k,'FOM_M'))*CapSolar(k,'capacity')*Ypv(k)) +

                 sum(w, (FCR_VRE*(1000*CapWind(w,'CAPEX_M') + CapWind(w,'trans_cap_cost')) + 1000*CapWind(w,'FOM_M'))*CapWind(w,'capacity')*Ywind(w))  +

                 sum(j, CRF(j)*(1000*StorageData('CostRatio',j)*StorageData('P_Capex',j)*Pcha(j) + 1000*(1-StorageData('CostRatio',j))*StorageData('P_Capex',j)*Pdis(j) + 1000*StorageData('E_Capex',j)*Ecap(j)))+

                 sum(j, 1000*StorageData('CostRatio',j)*StorageData('FOM',j)*Pcha(j) + 1000*(1-StorageData('CostRatio',j))*StorageData('FOM',j)*Pdis(j) + StorageData('VOM',j)*sum(h,PD(j,h)))+

                  sum(bu,CRF_GasCC(bu)*1000*DataBU(bu,'Capex')*CapCC(bu) + DataBU(bu,'FuelCost')*DataBU(bu,'HeatRate')*sum(h, GenCC(h,bu)) + DataBU(bu,'FOM')*1000*CapCC(bu) + DataBU(bu,'VOM')*sum(h, GenCC(h,bu))) 
                 
                 + sum(h, ImportPrices(h)*Imports(h))- sum(h, ExportPrices(h)*Exports(h))
                 
                 + sum(m,Fixed_dem_charge(m) + Peak_variable_dem_charge(m) + Offpeak_variable_dem_charge(m));

SupplyDes(h)$(h_step1(h) and %ResilienceOption%=1)..      Load(h)+sum(j, PC(j,h)) + Exports(h) - AlphaNuclear*Nuclear(h) - AlphaLargHy*LargeHydro(h) - AlphaOtheRe*OtherRenewables(h) - GenPV(h) - GenWind(h) - sum(j,PD(j,h)) - sum(bu,GenCC(h,bu)) - Imports(h) =e= 0;

GenMix_ShareDes..   sum(h$h_step1(h), sum(bu, GenCC(h,bu)) + Imports(h)) =l= (1-GenMix_Target)*sum(h$h_step1(h),Load(h) + sum(j, PC(j,h)) - sum(j,PD(j,h)) );

SolarBalDes(h)$(h_step1(h) and %ResilienceOption%=1)..    GenPV(h)+ CurtPV(h) =e= sum(k, CFSolar(h,k)*CapSolar(k,'capacity')*Ypv(k));

WindBalDes(h)$(h_step1(h) and %ResilienceOption%=1)..     GenWind(h)+ CurtWind(h) =e= sum(w, CFWind(h,w)*CapWind(w,'capacity')*Ywind(w));

HydroBudgetDes(hhh)$(h_step1(hhh) and %ResilienceOption%=1).. sum (h$(ord(h)> 24*(ord(hhh)-1) and ord(h)<=24*ord(hhh)),LargeHydro(h)) =e= sum (h$(ord(h)> 24*(ord(hhh)-1) and ord(h)<=24*ord(hhh)),LargeHydroBudget(h));  

ChargStDes(j,h)$(h_step1(h) and %ResilienceOption%=1)..   PC(j,h) =l= StorageData('Max_P',j)*Ystorage(j,h);

DischargStDes(j,h)$(h_step1(h) and %ResilienceOption%=1)..  PD(j,h) =l= StorageData('Max_P',j)*(1-Ystorage(j,h));

MaxPCDes(j,h)$(h_step1(h) and %ResilienceOption%=1)..     PC(j,h) =l= Pcha(j);

MaxPDDes(j,h)$(h_step1(h) and %ResilienceOption%=1)..     PD(j,h) =l= Pdis(j);

MaxSOCDes(j,h)$(h_step1(h) and %ResilienceOption%=1)..    SOC(j,h) =l= Ecap(j);

Supply(h)..      Load(h)+sum(j, PC(j,h)) + Exports(h) -AlphaNuclear*Nuclear(h)-AlphaLargHy*LargeHydro(h)-AlphaOtheRe*OtherRenewables(h)-GenPV(h)-GenWind(h)-sum(j,PD(j,h))-sum(bu, GenCC(h,bu)) - Imports(h) =e=0;

GenMix_Share..   sum(h, sum(bu, GenCC(h,bu)) + Imports(h)) =l= (1-GenMix_Target)*sum(h,Load(h) + sum(j, PC(j,h)) - sum(j,PD(j,h)));

Fixed_demand_charge(hm(h,m))$(%DemandCharges%=1)..  Fixed_dem_charge(m) =g= fixed_dem_rate(h) * Imports(h) ;

Peak_variable_demand_charge(hm(h,m))$(peak(h) and %DemandCharges%=1)..  Peak_variable_dem_charge(m) =g= variable_dem_rate(h) * Imports(h);

Offpeak_variable_demand_charge(hm(h,m))$(offpeak(h) and %DemandCharges%=1)..  OffPeak_variable_dem_charge(m) =g= variable_dem_rate(h) * Imports(h) ;

SolarBal(h)..    GenPV(h)+ CurtPV(h) =e= sum(k, CFSolar(h,k)*CapSolar(k,'capacity')*Ypv(k));

WindBal(h)..     GenWind(h)+ CurtWind(h) =e= sum(w, CFWind(h,w)*CapWind(w,'capacity')*Ywind(w));

Footprint..      sum(k,pv_footprint * CapSolar(k,'capacity') * Ypv(k)) + sum(w,wind_footprint * CapWind(w,'capacity') * Ywind(w)) =l= total_available_footprint ; 

HydroBudget(hhh).. sum (h$(ord(h)> 24*(ord(hhh)-1) and ord(h)<=24*ord(hhh)),LargeHydro(h)) =e= sum (h$(ord(h)> 24*(ord(hhh)-1) and ord(h)<=24*ord(hhh)),LargeHydroBudget(h));  

ChargSt(j,h)..   PC(j,h) =l= StorageData('Max_P',j)*Ystorage(j,h);

DischargSt(j,h)..  PD(j,h) =l= StorageData('Max_P',j)*(1-Ystorage(j,h));

MaxPC(j,h)..     PC(j,h) =l= Pcha(j);

MaxPD(j,h)..     PD(j,h) =l= Pdis(j);

MaxSOC(j,h)..    SOC(j,h) =l= Ecap(j);

SOCBalDes(j,h)$(h_step1(h) and ord(h) > 1  and %ResilienceOption%=1)..       SOC(j,h) =e= sum(hh$(ord(hh) = ord(h) -1), SOC(j,hh))+ sqrt(StorageData('Eff',j))*PC(j,h)-(1/sqrt(StorageData('Eff',j)))*PD(j,h);

SOCBal(j,h)$(ord(h) > 1)..       SOC(j,h) =e= sum(hh$(ord(hh) = ord(h) -1), SOC(j,hh))+ sqrt(StorageData('Eff',j))*PC(j,h)-(1/sqrt(StorageData('Eff',j)))*PD(j,h);

IniBal(j,h)$(ord(h) = 1)..       SOC(j,h) =e= sum(hh $ (ord(hh) = card(hh)), SOC(j,hh)) + sqrt(StorageData('Eff',j))*PC(j,h)-(1/sqrt(StorageData('Eff',j)))*PD(j,h);

MaxPcha(j)..     Pcha(j) =l= StorageData('Max_P',j);

MaxPdis(j)..     Pdis(j) =l= StorageData('Max_P',j);

PchaPdisDes(j)$(%ResilienceOption%=1 and sum(h,h_step1(h)))..    Pcha(j) =e= Pdis(j);

PchaPdis(b)..    Pcha(b) =e= Pdis(b);

MinEcap(j)..     Ecap(j) =g= StorageData('Min_Duration',j)*(1/sqrt(StorageData('Eff',j)))*Pdis(j);

MaxEcap(j)..     Ecap(j) =l= StorageData('Max_Duration',j)*(1/sqrt(StorageData('Eff',j)))*Pdis(j);

BackupGenDes(bu,h)$h_step1(h)..   CapCC(bu) =g= GenCC(h,bu);

BackupGen(bu,h)..   CapCC(bu) =g= GenCC(h,bu);

MaxCycleYear..   sum(h,PD('Li-Ion',h)) =l= (MaxCycles/StorageData('Lifetime','Li-Ion'))*Ecap('Li-Ion') ;

BackupEnergyOutage(j,h)$(ord(h)<outage_start_hour or ord(h)>(outage_start_hour + max_backup_power_dur + SOC_restore_hours) and %ResilienceOption%=1).. sqrt(StorageData('Eff',j))*SOC(j,h) =g= BackupSOC(j);

*****************
$offlisting
$offsymxref offsymlist
*****************

Model TechMix
                /Obj
                 Supply
                 GenMix_Share
                 Fixed_demand_charge
                 Peak_variable_demand_charge
                 Offpeak_variable_demand_charge
                 SolarBal
                 WindBal
*                 Footprint
                 HydroBudget
                 ChargSt
                 DischargSt
                 MaxPC
                 MaxPD
                 MaxSOC
                 SOCBal
                 IniBal
                 MaxPcha
                 MaxPdis
                 PchaPdis
                 MinEcap
                 MaxEcap
                 BackupGen
                 MaxCycleYear
                 /;

Model SDOM_ResDesign
                /Obj
                 SupplyDes
                 GenMix_ShareDes
                 SolarBalDes
                 WindBalDes
*                 Footprint
                 HydroBudgetDes
                 ChargStDes
                 DischargStDes
                 MaxPCDes
                 MaxPDDes
                 MaxSOCDes
                 SOCBalDes
                 MaxPcha
                 MaxPdis
                 PchaPdisDes
                 MinEcap
                 MaxEcap
                 BackupGenDes
                 MaxCycleYear         
                 / ;

Model SDOM_ResOutage
                /Obj
                 Supply
                 GenMix_Share
                 Fixed_demand_charge
                 Peak_variable_demand_charge
                 Offpeak_variable_demand_charge
                 SolarBal
                 WindBal
*                 Footprint
                 HydroBudget
                 ChargSt
                 DischargSt
                 MaxPC
                 MaxPD
                 MaxSOC
                 SOCBal
                 IniBal
                 MaxPcha
                 MaxPdis
                 PchaPdis
                 MinEcap
                 MaxEcap
                 BackupGen
                 MaxCycleYear         
                 BackupEnergyOutage
                 / ;
                 


option optcr=0.05;

Option resLim = 1000000;

Option mip = cplex;
$ontext
$onecho > cbc.opt
presolve on
threads 4       
$offecho

$onecho > cplex.opt
threads 4       
$offecho
$offtext
TechMix.OptFile = 1;

*$ONTEXT
option limrow=0;
option limcol=0;
option solprint = off;
option sysout = off;
*$OFFTEXT


Parameter
         TotalCapCC(Runs) Total capacity of gas combined cycle units (MW)
         TotalCapPV(Runs) Total capacity of solar PV units (MW)
         TotalCapWind(Runs) Total capacity of wind units (MW)
         TotalCapScha(Runs,j) Total charge power capacity of storage units j (MW)
         TotalCapSdis(Runs,j) Total discharge power capacity of storage units j (MW)
         TotalEcapS(Runs,j) Total energy capacity of storage units j (MW)
         TotalGenGasCC(Runs) Total generation from Gas CC units (MWh)
         TotalGenPV(Runs) Total generation from solar PV units (MWh)
         TotalGenWind(Runs) Total generation from wind units (MWh)
         TotalOtherRen(Runs) Total generation from other renewable units (MWh)
         TotalHydro(Runs) Total generation from hydro units (MWh)
         TotalNuclear(Runs) Total generation from nuclear units (MWh)
         TotalGenS(Runs,j) Total generation from storage units j (MWh)
         TotalCost(Runs) Total cost US$
         TotalPCarge(Runs,j) Total charged energy for storage unit j (MWh)
         TotalAllPCarge(Runs) Total charged energy for all storage units j (MWh)
         SummaryPC(Runs,h,j) Charging power for storage technology j during hour h (MW)
         SummaryPD(Runs,h,j) Discharging power for storage technology j during hour h (MW)
         SummarySOC(Runs,h,j) State-of-charge (SOC) for storage technology j during hour h (MWh)
         SummaryD(Runs,j) Discharge duration for storage technology j (h)
         SolarPVGen(Runs,h) Generation from solar PV plants
         WindGen(Runs,h) Generation from wind plants
         SolarPVCurt(Runs,h) Curtailment from solar PV plants
         WindCurt(Runs,h) Curtailment from wind plants
         GenGasCC(Runs,h) Generation from gas CC unit
         ImportsPower(Runs,h) Power Imports
         ExportsPower(Runs,h) Power Imports
         HydroGene(Runs,h) Hydropower generation 
         StorageGasCC2Storage(Runs,h) Power from Storage and Gas CC to Storage
         SelectedSolarPV(Runs,k) Selected Solar PV plants
         SelectedWind(Runs,w) Selected Wind plants
         SolarCapex(Runs) Total Capex for solar PV
         WindCapex(Runs) Total Capex for wind
         SolarFOM(Runs) Total FOM for solar PV
         WindFOM(Runs) Total FOM for wind
         Li_Ion_Pcapex(Runs) Total Power Capex for Li-Ion
         Li_Ion_Ecapex(Runs) Total Energy Capex for Li-Ion
         Li_Ion_FOM(Runs) Total FOM for Li-Ion
         Li_Ion_VOM(Runs) Total VOM for Li-Ion
         Vanadium_Pcapex(Runs) Total Power Capex for Vanadium
         Vanadium_Ecapex(Runs) Total Energy Capex for Vanadium
         Vanadium_FOM(Runs) Total FOM for Vanadium
         Vanadium_VOM(Runs) Total VOM for Vanadium
         PHS_Pcapex(Runs) Total Power Capex for PHS
         PHS_Ecapex(Runs) Total Energy Capex for PHS
         PHS_FOM(Runs) Total FOM for PHS
         PHS_VOM(Runs) Total VOM for PHS
         H2_Pcapex(Runs) Total Power Capex for H2
         H2_Ecapex(Runs) Total Energy Capex for H2
         H2_FOM(Runs) Total FOM for H2
         H2_VOM(Runs) Total VOM for H2
         GasCC_Capex(Runs) Total Gas CC Capex
         GasCC_FOM(Runs) Total Gas CC FOM
         GasCC_VOM(Runs) Total Gas CC VOM
         GasCC_FUEL(Runs) Total Gas CC fuel cost
         ImportsCost(Runs) Total cost of imports
         ExportsCost(Runs) Total cost of exports
         DemandCharges(Runs) Total demand charges
;

if(%ResilienceOption%=1,
    loop (Runs,

         Ypv.fx(k)   = 0;
         Ywind.fx(w) = 0;
         Load(h) = critical_peak_load ; 
         CapCC.fx(bu) = 0 ;
         Imports.fx(h) = 0 ;
         Exports.fx(h) = 0 ; 
         GenMix_Target = 0 ;
         LargeHydro(h) = 0 ;
         OtherRenewables(h) = 0;
         Nuclear(h) = 0 ;
         Solve SDOM_ResDesign using mip minimizing TSC;

         Load(h) = Load_step2(h) ; 
         CapCC.up(bu) = smax (h, Load(h)-AlphaNuclear*Nuclear(h)-AlphaLargHy*LargeHydro(h)-AlphaOtheRe*OtherRenewables(h));
         CapCC.fx(bu) = 0 ;
         GenCC.fx(h,bu)$(ord(h)>= outage_start_hour and ord(h)<= outage_start_hour + max_backup_power_dur) =0;
         Imports.up(h) = ImportCap(h);
         Exports.up(h) = ExportCap(h);
         GenMix_Target = GenMix_Target_step2 ;
         Pdis.lo(j) = Pdis.l(j) ;
         Pcha.lo(j) = Pcha.l(j) ;
         Ecap.lo(j) = Ecap.l(j) ;
         BackupSOC(j) = SOC.l(j,'1') ; 
         Ypv.up(k)   = 1;
         Ywind.up(w) = 1;
         Exports.fx(h) = 0 ; 
         Solve SDOM_ResOutage using mip minimizing TSC;
    
         TotalCost(Runs) = TSC.l;
         TotalCapCC(Runs) = sum(bu,CapCC.l(bu));
         TotalCapPV(Runs) = sum(k, CapSolar(k,'capacity')*Ypv.l(k));
         TotalCapWind(Runs) = sum(w, CapWind(w,'capacity')*Ywind.l(w));
         TotalCapScha(Runs,j) = Pcha.l(j);
         TotalCapSdis(Runs,j) = Pdis.l(j);
         TotalEcapS(Runs,j) = Ecap.l(j);
         TotalGenGasCC(Runs) = sum((h,bu),GenCC.l(h,bu));
         TotalGenPV(Runs) = sum(h, GenPV.l(h));
         TotalGenWind(Runs) = sum(h, GenWind.l(h));
         TotalGenS(Runs,j) = sum((h),PD.l(j,h));
         TotalOtherRen(Runs) = sum(h, OtherRenewables(h));
         TotalHydro(Runs) = sum(h, LargeHydro(h));
         TotalNuclear(Runs) = sum(h, Nuclear(h));
         SummaryPC(Runs,h,j) = PC.l(j,h);
         TotalPCarge(Runs,j) = sum(h,SummaryPC(Runs,h,j));
         TotalAllPCarge(Runs) = sum(j,TotalPCarge(Runs,j)) ; 
         SummaryPD(Runs,h,j) = PD.l(j,h);
         SummarySOC(Runs,h,j) = SOC.l(j,h);
         SummaryD(Runs,j) = sqrt(StorageData('Eff',j))*Ecap.l(j)/(Pdis.l(j) + 1e-15);
         SolarPVGen(Runs,h) = GenPV.l(h);
         WindGen(Runs,h) = GenWind.l(h);
         SolarPVCurt(Runs,h) = CurtPV.l(h);
         WindCurt(Runs,h) = CurtWind.l(h);
         GenGasCC(Runs,h) = sum(bu,GenCC.l(h,bu));
         ImportsPower(Runs,h) = Imports.l(h);
         ExportsPower(Runs,h) = Exports.l(h);
         HydroGene(Runs,h) = LargeHydro(h);
         SelectedSolarPV(Runs,k) = Ypv.l(k);
         SelectedWind(Runs,w) = Ywind.l(w);
         StorageGasCC2Storage(Runs,h) = (sum(j, PD.l(j,h)) + sum(bu,GenCC.l(h,bu)))$(Load(h)-AlphaNuclear*Nuclear(h)-AlphaLargHy*LargeHydro(h)-AlphaOtheRe*OtherRenewables(h)-GenPV.l(h)-GenWind.l(h) <= 0) +
                                     sum(j, PC.l(j,h))$(Load(h)-AlphaNuclear*Nuclear(h)-AlphaLargHy*LargeHydro(h)-AlphaOtheRe*OtherRenewables(h)-GenPV.l(h)-GenWind.l(h) > 0) ;
         SolarCapex(Runs) = sum(k, (FCR_VRE*(1000*CapSolar(k,'CAPEX_M') + CapSolar(k,'trans_cap_cost'))*CapSolar(k,'capacity')*Ypv.l(k)));
         WindCapex(Runs) = sum(w, (FCR_VRE*(1000*CapWind(w,'CAPEX_M') + CapWind(w,'trans_cap_cost'))*CapWind(w,'capacity')*Ywind.l(w)));
         SolarFOM(Runs) = sum(k, 1000*CapSolar(k,'FOM_M')*CapSolar(k,'capacity')*Ypv.l(k));
         WindFOM(Runs) = sum(w, 1000*CapWind(w,'FOM_M')*CapWind(w,'capacity')*Ywind.l(w));
         Li_Ion_Pcapex(Runs) = CRF('Li-Ion')*(1000*StorageData('CostRatio','Li-Ion')*StorageData('P_Capex','Li-Ion')*Pcha.l('Li-Ion') + 1000*(1-StorageData('CostRatio','Li-Ion'))*StorageData('P_Capex','Li-Ion')*Pdis.l('Li-Ion') );
         Li_Ion_Ecapex(Runs)  = CRF('Li-Ion')*1000*StorageData('E_Capex','Li-Ion')*Ecap.l('Li-Ion');
         Vanadium_Pcapex(Runs) = CRF('Vanadium')*(1000*StorageData('CostRatio','Vanadium')*StorageData('P_Capex','Vanadium')*Pcha.l('Vanadium') + 1000*(1-StorageData('CostRatio','Vanadium'))*StorageData('P_Capex','Vanadium')*Pdis.l('Vanadium') );
         Vanadium_Ecapex(Runs)  = CRF('Vanadium')*1000*StorageData('E_Capex','Vanadium')*Ecap.l('Vanadium');
         PHS_Pcapex(Runs) = CRF('PHS')*(1000*StorageData('CostRatio','PHS')*StorageData('P_Capex','PHS')*Pcha.l('PHS') + 1000*(1-StorageData('CostRatio','PHS'))*StorageData('P_Capex','PHS')*Pdis.l('PHS') );
         PHS_Ecapex(Runs)  = CRF('PHS')*1000*StorageData('E_Capex','PHS')*Ecap.l('PHS');
         H2_Pcapex(Runs) = CRF('H2')*(1000*StorageData('CostRatio','H2')*StorageData('P_Capex','H2')*Pcha.l('H2') + 1000*(1-StorageData('CostRatio','H2'))*StorageData('P_Capex','H2')*Pdis.l('H2') );
         H2_Ecapex(Runs)  = CRF('H2')*1000*StorageData('E_Capex','H2')*Ecap.l('H2');
         Li_Ion_FOM(Runs) = 1000*StorageData('CostRatio','Li-Ion')*StorageData('FOM','Li-Ion')*Pcha.l('Li-Ion') + 1000*(1-StorageData('CostRatio','Li-Ion'))*StorageData('FOM','Li-Ion')*Pdis.l('Li-Ion') ;
         Li_Ion_VOM(Runs) = StorageData('VOM','Li-Ion')*sum(h,PD.l('Li-Ion',h));
         Vanadium_FOM(Runs) = 1000*StorageData('CostRatio','Vanadium')*StorageData('FOM','Vanadium')*Pcha.l('Vanadium') + 1000*(1-StorageData('CostRatio','Vanadium'))*StorageData('FOM','Vanadium')*Pdis.l('Vanadium') ;
         Vanadium_VOM(Runs) = StorageData('VOM','Vanadium')*sum(h,PD.l('Vanadium',h));
         PHS_FOM(Runs) = 1000*StorageData('CostRatio','PHS')*StorageData('FOM','PHS')*Pcha.l('PHS') + 1000*(1-StorageData('CostRatio','PHS'))*StorageData('FOM','PHS')*Pdis.l('PHS') ;
         PHS_VOM(Runs) = StorageData('VOM','PHS')*sum(h,PD.l('PHS',h));
         H2_FOM(Runs) = 1000*StorageData('CostRatio','H2')*StorageData('FOM','H2')*Pcha.l('H2') + 1000*(1-StorageData('CostRatio','H2'))*StorageData('FOM','H2')*Pdis.l('H2') ;
         H2_VOM(Runs) = StorageData('VOM','H2')*sum(h,PD.l('H2',h));
         GasCC_Capex(Runs) = FCR_GasCC*1000*CapexGasCC*sum(bu,CapCC.l(bu));
         GasCC_FOM(Runs) = FOM_GasCC*1000*sum(bu,CapCC.l(bu));
         GasCC_VOM(Runs) = VOM_GasCC*sum((h,bu), GenCC.l(h,bu));
         GasCC_FUEL(Runs) = GasPrice*HR*sum((h,bu), GenCC.l(h,bu));
         ImportsCost(Runs) = sum(h, ImportPrices(h)*Imports.l(h));
         ExportsCost(Runs) = -sum(h, ExportPrices(h)*Exports.l(h));
         DemandCharges(Runs) = sum(m,Fixed_dem_charge.l(m) + Peak_variable_dem_charge.l(m) + Offpeak_variable_dem_charge.l(m)) ;
    
        );
    elseif %ResilienceOption%=0,
        loop (Runs,
         CapCC.up(bu) = smax (h, Load(h)-AlphaNuclear*Nuclear(h)-AlphaLargHy*LargeHydro(h)-AlphaOtheRe*OtherRenewables(h));
         CapCC.up(bu) = DataBU(bu,'MaxCapacity');
         CapCC.lo(bu) = DataBU(bu,'MinCapacity');
         Solve TechMix using mip minimizing TSC;
    
         TotalCost(Runs) = TSC.l;
         TotalCapCC(Runs) = sum(bu,CapCC.l(bu));
         TotalCapPV(Runs) = sum(k, CapSolar(k,'capacity')*Ypv.l(k));
         TotalCapWind(Runs) = sum(w, CapWind(w,'capacity')*Ywind.l(w));
         TotalCapScha(Runs,j) = Pcha.l(j);
         TotalCapSdis(Runs,j) = Pdis.l(j);
         TotalEcapS(Runs,j) = Ecap.l(j);
         TotalGenGasCC(Runs) = sum((h,bu),GenCC.l(h,bu));
         TotalGenPV(Runs) = sum(h, GenPV.l(h));
         TotalGenWind(Runs) = sum(h, GenWind.l(h));
         TotalGenS(Runs,j) = sum((h),PD.l(j,h));
         TotalOtherRen(Runs) = sum(h, OtherRenewables(h));
         TotalHydro(Runs) = sum(h, LargeHydro(h));
         TotalNuclear(Runs) = sum(h, Nuclear(h));
         SummaryPC(Runs,h,j) = PC.l(j,h);
         TotalPCarge(Runs,j) = sum(h,SummaryPC(Runs,h,j));
         TotalAllPCarge(Runs) = sum(j,TotalPCarge(Runs,j)) ; 
         SummaryPD(Runs,h,j) = PD.l(j,h);
         SummarySOC(Runs,h,j) = SOC.l(j,h);
         SummaryD(Runs,j) = sqrt(StorageData('Eff',j))*Ecap.l(j)/(Pdis.l(j) + 1e-15);
         SolarPVGen(Runs,h) = GenPV.l(h);
         WindGen(Runs,h) = GenWind.l(h);
         SolarPVCurt(Runs,h) = CurtPV.l(h);
         WindCurt(Runs,h) = CurtWind.l(h);
         GenGasCC(Runs,h) = sum(bu,GenCC.l(h,bu));
         ImportsPower(Runs,h) = Imports.l(h);
         ExportsPower(Runs,h) = Exports.l(h);
         HydroGene(Runs,h) = LargeHydro(h);
         SelectedSolarPV(Runs,k) = Ypv.l(k);
         SelectedWind(Runs,w) = Ywind.l(w);
         StorageGasCC2Storage(Runs,h) = (sum(j, PD.l(j,h)) + sum(bu,GenCC.l(h,bu)))$(Load(h)-AlphaNuclear*Nuclear(h)-AlphaLargHy*LargeHydro(h)-AlphaOtheRe*OtherRenewables(h)-GenPV.l(h)-GenWind.l(h) <= 0) +
                                     sum(j, PC.l(j,h))$(Load(h)-AlphaNuclear*Nuclear(h)-AlphaLargHy*LargeHydro(h)-AlphaOtheRe*OtherRenewables(h)-GenPV.l(h)-GenWind.l(h) > 0) ;
         SolarCapex(Runs) = sum(k, (FCR_VRE*(1000*CapSolar(k,'CAPEX_M') + CapSolar(k,'trans_cap_cost'))*CapSolar(k,'capacity')*Ypv.l(k)));
         WindCapex(Runs) = sum(w, (FCR_VRE*(1000*CapWind(w,'CAPEX_M') + CapWind(w,'trans_cap_cost'))*CapWind(w,'capacity')*Ywind.l(w)));
         SolarFOM(Runs) = sum(k, 1000*CapSolar(k,'FOM_M')*CapSolar(k,'capacity')*Ypv.l(k));
         WindFOM(Runs) = sum(w, 1000*CapWind(w,'FOM_M')*CapWind(w,'capacity')*Ywind.l(w));
         Li_Ion_Pcapex(Runs) = CRF('Li-Ion')*(1000*StorageData('CostRatio','Li-Ion')*StorageData('P_Capex','Li-Ion')*Pcha.l('Li-Ion') + 1000*(1-StorageData('CostRatio','Li-Ion'))*StorageData('P_Capex','Li-Ion')*Pdis.l('Li-Ion') );
         Li_Ion_Ecapex(Runs)  = CRF('Li-Ion')*1000*StorageData('E_Capex','Li-Ion')*Ecap.l('Li-Ion');
         Vanadium_Pcapex(Runs) = CRF('Vanadium')*(1000*StorageData('CostRatio','Vanadium')*StorageData('P_Capex','Vanadium')*Pcha.l('Vanadium') + 1000*(1-StorageData('CostRatio','Vanadium'))*StorageData('P_Capex','Vanadium')*Pdis.l('Vanadium') );
         Vanadium_Ecapex(Runs)  = CRF('Vanadium')*1000*StorageData('E_Capex','Vanadium')*Ecap.l('Vanadium');
         PHS_Pcapex(Runs) = CRF('PHS')*(1000*StorageData('CostRatio','PHS')*StorageData('P_Capex','PHS')*Pcha.l('PHS') + 1000*(1-StorageData('CostRatio','PHS'))*StorageData('P_Capex','PHS')*Pdis.l('PHS') );
         PHS_Ecapex(Runs)  = CRF('PHS')*1000*StorageData('E_Capex','PHS')*Ecap.l('PHS');
         H2_Pcapex(Runs) = CRF('H2')*(1000*StorageData('CostRatio','H2')*StorageData('P_Capex','H2')*Pcha.l('H2') + 1000*(1-StorageData('CostRatio','H2'))*StorageData('P_Capex','H2')*Pdis.l('H2') );
         H2_Ecapex(Runs)  = CRF('H2')*1000*StorageData('E_Capex','H2')*Ecap.l('H2');
         Li_Ion_FOM(Runs) = 1000*StorageData('CostRatio','Li-Ion')*StorageData('FOM','Li-Ion')*Pcha.l('Li-Ion') + 1000*(1-StorageData('CostRatio','Li-Ion'))*StorageData('FOM','Li-Ion')*Pdis.l('Li-Ion') ;
         Li_Ion_VOM(Runs) = StorageData('VOM','Li-Ion')*sum(h,PD.l('Li-Ion',h));
         Vanadium_FOM(Runs) = 1000*StorageData('CostRatio','Vanadium')*StorageData('FOM','Vanadium')*Pcha.l('Vanadium') + 1000*(1-StorageData('CostRatio','Vanadium'))*StorageData('FOM','Vanadium')*Pdis.l('Vanadium') ;
         Vanadium_VOM(Runs) = StorageData('VOM','Vanadium')*sum(h,PD.l('Vanadium',h));
         PHS_FOM(Runs) = 1000*StorageData('CostRatio','PHS')*StorageData('FOM','PHS')*Pcha.l('PHS') + 1000*(1-StorageData('CostRatio','PHS'))*StorageData('FOM','PHS')*Pdis.l('PHS') ;
         PHS_VOM(Runs) = StorageData('VOM','PHS')*sum(h,PD.l('PHS',h));
         H2_FOM(Runs) = 1000*StorageData('CostRatio','H2')*StorageData('FOM','H2')*Pcha.l('H2') + 1000*(1-StorageData('CostRatio','H2'))*StorageData('FOM','H2')*Pdis.l('H2') ;
         H2_VOM(Runs) = StorageData('VOM','H2')*sum(h,PD.l('H2',h));
         GasCC_Capex(Runs) = FCR_GasCC*1000*CapexGasCC*sum(bu,CapCC.l(bu));
         GasCC_FOM(Runs) = FOM_GasCC*1000*sum(bu,CapCC.l(bu));
         GasCC_VOM(Runs) = VOM_GasCC*sum((h,bu), GenCC.l(h,bu));
         GasCC_FUEL(Runs) = GasPrice*HR*sum((h,bu), GenCC.l(h,bu));
         ImportsCost(Runs) = sum(h, ImportPrices(h)*Imports.l(h));
         ExportsCost(Runs) = -sum(h, ExportPrices(h)*Exports.l(h));
         DemandCharges(Runs) = sum(m,Fixed_dem_charge.l(m) + Peak_variable_dem_charge.l(m) + Offpeak_variable_dem_charge.l(m)) ;
    
        );
);

FILE csv Report File /OutputSummary.csv/;
PUT csv
put_utility 'ren' / '%outdir%\%case_name%\%sim_year%_OutputSummary_SDOM_%FNAME%_Nuclear_' AlphaNuclear:0:0 '_Target_' GenMix_Target:00 '_Resilience_' %ResilienceOption%:00 '.csv';
csv.pc = 5;
PUT csv;

PUT 'Metric','Technology','Scenario','Optimal Value','Unit'/;

loop (Runs,
     PUT 'Total cost', '', Runs.tl, TotalCost(Runs):0:5, 'US$' /);

loop (Runs,
     PUT 'Capacity', 'GasCC', Runs.tl, TotalCapCC(Runs):0:5, 'MW' /);

loop (Runs,
     PUT 'Capacity', 'Solar PV', Runs.tl, TotalCapPV(Runs):0:5, 'MW' /);

loop (Runs,
     PUT 'Capacity', 'Wind', Runs.tl, TotalCapWind(Runs):0:5, 'MW' /);
     
loop (Runs,
     PUT 'Capacity', 'All', Runs.tl, (TotalCapWind(Runs) + TotalCapPV(Runs) + TotalCapCC(Runs)):0:5, 'MW' /);
     
loop (Runs,
     PUT 'Total generation', 'GasCC', Runs.tl, TotalGenGasCC(Runs):0:5, 'MWh' /);

loop (Runs,
     PUT 'Total generation', 'Solar PV', Runs.tl, TotalGenPV(Runs):0:5, 'MWh' /);

loop (Runs,
     PUT 'Total generation', 'Wind', Runs.tl, TotalGenWind(Runs):0:5, 'MWh' /);
     
loop (Runs,
     PUT 'Total generation', 'Other renewables', Runs.tl, TotalOtherRen(Runs):0:5, 'MWh' /);

loop (Runs,
     PUT 'Total generation', 'Hydro', Runs.tl, TotalHydro(Runs):0:5, 'MWh' /);
     
loop (Runs,
     PUT 'Total generation', 'Nuclear', Runs.tl, TotalNuclear(Runs):0:5, 'MWh' /);
     
loop ((Runs,j),
     PUT 'Total generation', j.tl, Runs.tl, TotalGenS(Runs,j):0:5, 'MWh' /);
     
loop (Runs,
     PUT 'Total generation', 'All', Runs.tl, (TotalGenGasCC(Runs) + TotalGenPV(Runs) + TotalGenWind(Runs) + TotalOtherRen(Runs) + TotalHydro(Runs) + TotalNuclear(Runs) + sum(j,TotalGenS(Runs,j))):0:5, 'MWh' /);
     
loop (Runs,
     PUT 'Imports', 'Total Imports/Exports', Runs.tl, sum(h,ImportsPower(Runs,h)):0:5, 'MWh' /);
     
loop (Runs,
     PUT 'Exports', 'Total Imports/Exports', Runs.tl, sum(h,ExportsPower(Runs,h)):0:5, 'MWh' /);
     
loop ((Runs,j),
     PUT 'Storage energy charging', j.tl, Runs.tl, TotalPCarge(Runs,j):0:5, 'MWh' /);
     
loop (Runs,
     PUT 'Storage energy charging', 'All', Runs.tl, TotalAllPCarge(Runs):0:5, 'MWh' /);
     
loop (Runs,
     PUT 'Total demand', '', Runs.tl, sum(h, Load(h)):0:5, 'MWh' /);

loop (Runs,
     PUT 'CAPEX', 'GasCC', Runs.tl, GasCC_Capex(Runs):0:5, 'US$' /);

loop (Runs,
     PUT 'CAPEX', 'Solar PV', Runs.tl, SolarCapex(Runs):0:5, 'US$' /);

loop (Runs,
     PUT 'CAPEX', 'Wind', Runs.tl, WindCapex(Runs):0:5, 'US$' /);

loop (Runs,
     PUT 'CAPEX', 'All', Runs.tl, (GasCC_Capex(Runs) + SolarCapex(Runs) + WindCapex(Runs)):0:5, 'US$' /);      

loop (Runs,
     PUT 'Power Capex', 'Li-Ion', Runs.tl, Li_Ion_Pcapex(Runs):0:5, 'US$' /);
     
loop (Runs,
     PUT 'Power Capex', 'Vanadium', Runs.tl, Vanadium_Pcapex(Runs):0:5, 'US$' /);
     
loop (Runs,
     PUT 'Power Capex', 'PHS', Runs.tl, PHS_Pcapex(Runs):0:5, 'US$' /);
     
loop (Runs,
     PUT 'Power Capex', 'H2', Runs.tl, H2_Pcapex(Runs):0:5, 'US$' /);

loop (Runs,
     PUT 'Total Power Capex', 'All', Runs.tl, (Li_Ion_Pcapex(Runs) + Vanadium_Pcapex(Runs) + PHS_Pcapex(Runs) + H2_Pcapex(Runs)):0:5, 'US$' /);
     
loop (Runs,
     PUT 'Energy Capex', 'Li-Ion', Runs.tl, Li_Ion_Ecapex(Runs):0:5, 'US$' /);

loop (Runs,
     PUT 'Energy Capex', 'Vanadium', Runs.tl, Vanadium_Ecapex(Runs):0:5, 'US$' /);
     
loop (Runs,
     PUT 'Energy Capex', 'PHS', Runs.tl, PHS_Ecapex(Runs):0:5, 'US$' /);
     
loop (Runs,
     PUT 'Energy Capex', 'H2', Runs.tl, H2_Ecapex(Runs):0:5, 'US$' /);
     
loop (Runs,
     PUT 'Energy Capex', 'All', Runs.tl, (Li_Ion_Ecapex(Runs) + Vanadium_Ecapex(Runs) + PHS_Ecapex(Runs) + H2_Ecapex(Runs)):0:5, 'US$' /);

loop (Runs,
     PUT 'Total Capex', 'Li-Ion', Runs.tl, (Li_Ion_Ecapex(Runs) + Li_Ion_Pcapex(Runs)):0:5, 'US$' /);

loop (Runs,
     PUT 'Total Capex', 'Vanadium', Runs.tl, (Vanadium_Ecapex(Runs) + Vanadium_Pcapex(Runs)):0:5, 'US$' /);
     
loop (Runs,
     PUT 'Total Capex', 'PHS', Runs.tl, (PHS_Ecapex(Runs) + PHS_Pcapex(Runs)):0:5, 'US$' /);
     
loop (Runs,
     PUT 'Total Capex', 'H2', Runs.tl, (H2_Ecapex(Runs) + H2_Pcapex(Runs)):0:5, 'US$' /);
     
loop (Runs,
     PUT 'Total Capex', 'All', Runs.tl, (Li_Ion_Pcapex(Runs) + Vanadium_Pcapex(Runs) + PHS_Pcapex(Runs) + H2_Pcapex(Runs) + Li_Ion_Ecapex(Runs) + Vanadium_Ecapex(Runs) + PHS_Ecapex(Runs) + H2_Ecapex(Runs)):0:5, 'US$' /);
     

loop (Runs,
     PUT 'FOM', 'GasCC', Runs.tl, GasCC_FOM(Runs):0:5, 'US$' /);
     
loop (Runs,
     PUT 'FOM', 'Solar PV', Runs.tl, SolarFOM(Runs):0:5, 'US$' /);

loop (Runs,
     PUT 'FOM', 'Wind', Runs.tl, WindFOM(Runs):0:5, 'US$' /);

loop (Runs,
     PUT 'FOM', 'Li-Ion ', Runs.tl, Li_Ion_FOM(Runs):0:5, 'US$' /);
     
loop (Runs,
     PUT 'FOM', 'Vanadium', Runs.tl, Vanadium_FOM(Runs):0:5, 'US$' /);
     
loop (Runs,
     PUT 'FOM', 'PHS', Runs.tl, PHS_FOM(Runs):0:5, 'US$' /);
     
loop (Runs,
     PUT 'FOM', 'H2', Runs.tl, H2_FOM(Runs):0:5, 'US$' /);
     
loop (Runs,
     PUT 'FOM', 'All', Runs.tl, (GasCC_FOM(Runs) + SolarFOM(Runs) + WindFOM(Runs) + Li_Ion_FOM(Runs) + Vanadium_FOM(Runs) + PHS_FOM(Runs) + H2_FOM(Runs)):0:5, 'US$' /);
     
loop (Runs,
     PUT 'VOM', 'GasCC', Runs.tl, (GasCC_VOM(Runs) + GasCC_FUEL(Runs)):0:5, 'US$' /);

loop (Runs,
     PUT 'VOM', 'Li-Ion', Runs.tl, Li_Ion_VOM(Runs):0:5, 'US$' /);

loop (Runs,
     PUT 'VOM', 'Vanadium', Runs.tl, Vanadium_VOM(Runs):0:5, 'US$' /);

loop (Runs,
     PUT 'VOM', 'PHS', Runs.tl, PHS_VOM(Runs):0:5, 'US$' /);

loop (Runs,
     PUT 'VOM', 'H2', Runs.tl, H2_VOM(Runs):0:5, 'US$' /);

loop (Runs,
     PUT 'VOM', 'H2', Runs.tl, (GasCC_VOM(Runs) + GasCC_FUEL(Runs) + Li_Ion_VOM(Runs) + Vanadium_VOM(Runs) + PHS_VOM(Runs) + H2_VOM(Runs)):0:5, 'US$' /);
     
loop (Runs,
     PUT 'VOM', 'Import Cost', Runs.tl, ImportsCost(Runs):0:5, 'US$' /);
     
loop (Runs,
     PUT 'VOM', 'Export Cost', Runs.tl, ExportsCost(Runs):0:5, 'US$' /);
     
loop (Runs,
     PUT 'VOM', 'Demand Charges', Runs.tl, DemandCharges(Runs):0:5, 'US$' /);
     
loop (Runs,
     PUT 'OPEX', 'GasCC', Runs.tl, (GasCC_FOM(Runs) + GasCC_VOM(Runs) + GasCC_FUEL(Runs)):0:5, 'US$' /);
     
loop (Runs,
     PUT 'OPEX', 'Solar PV', Runs.tl, SolarFOM(Runs):0:5, 'US$' /);

loop (Runs,
     PUT 'OPEX', 'Wind', Runs.tl, WindFOM(Runs):0:5, 'US$' /);

loop (Runs,
     PUT 'OPEX', 'Li-Ion ', Runs.tl, (Li_Ion_FOM(Runs) + Li_Ion_VOM(Runs)):0:5, 'US$' /);
     
loop (Runs,
     PUT 'OPEX', 'Vanadium', Runs.tl, (Vanadium_FOM(Runs) + Vanadium_VOM(Runs)):0:5, 'US$' /);
     
loop (Runs,
     PUT 'OPEX', 'PHS', Runs.tl, (PHS_FOM(Runs) + PHS_VOM(Runs)):0:5, 'US$' /);
     
loop (Runs,
     PUT 'OPEX', 'H2', Runs.tl, (H2_FOM(Runs) + H2_VOM(Runs)):0:5, 'US$' /);
     
loop (Runs,
     PUT 'OPEX', 'All', Runs.tl, (GasCC_FOM(Runs) + SolarFOM(Runs) + WindFOM(Runs) + Li_Ion_FOM(Runs) + Vanadium_FOM(Runs) + PHS_FOM(Runs) + H2_FOM(Runs) + GasCC_VOM(Runs) + GasCC_FUEL(Runs) + Li_Ion_VOM(Runs) + Vanadium_VOM(Runs) + PHS_VOM(Runs) + H2_VOM(Runs)):0:5, 'US$' /);
  
loop ((Runs,j),
     PUT 'Charge power capacity', j.tl, Runs.tl,  TotalCapScha(Runs,j):0:5, 'MW' /);
     
loop (Runs,
     PUT 'Charge power capacity', 'All', Runs.tl,  sum(j,TotalCapScha(Runs,j)):0:5, 'MW' /);

loop ((Runs,j),
     PUT 'Discharge power capacity', j.tl, Runs.tl,  TotalCapSdis(Runs,j):0:5, 'MW' /);
     
loop (Runs,
     PUT 'Discharge power capacity', 'All', Runs.tl,  sum(j,TotalCapSdis(Runs,j)):0:5, 'MW' /);
     
loop ((Runs,j),
     PUT 'Average power capacity', j.tl, Runs.tl,  ((TotalCapScha(Runs,j) + TotalCapSdis(Runs,j))/2):0:5, 'MW' /);
     
loop (Runs,
     PUT 'Average power capacity', 'All', Runs.tl,  (sum(j,(TotalCapScha(Runs,j) + TotalCapSdis(Runs,j)))/2):0:5, 'MW' /);

loop ((Runs,j),
     PUT 'Energy capacity', j.tl, Runs.tl,  TotalEcapS(Runs,j):0:5, 'MWh' /);
     
loop (Runs,
     PUT 'Energy capacity', 'All', Runs.tl,  sum(j,TotalEcapS(Runs,j)):0:5, 'MWh' /);

loop ((Runs,j),
     PUT 'Discharge duration', j.tl, Runs.tl, SummaryD(Runs,j):0:5, 'h' /);
     
loop ((Runs,j),
     PUT 'Equivalent number of cycles', j.tl, Runs.tl, ((TotalGenS(Runs,j))/(TotalEcapS(Runs,j)+0.0001)):0:5, '-' /);

Putclose ;

FILE csvStorage Report File /OutputStorage.csv/;
PUT csvStorage
put_utility 'ren' / '%outdir%\%case_name%\%sim_year%_OutputStorage_SDOM_%FNAME%_Nuclear_' AlphaNuclear:0:0 '_Target_' GenMix_Target:00 '_Resilience_' %ResilienceOption%:00 '.csv';
csvStorage.pc = 5;
PUT csvStorage;

PUT 'Scenario', 'Technology', 'Hour', 'Charging power (MW)', 'Disharging power (MW)', 'State of charge (MWh)'  /;
loop ((Runs,h,j),
     PUT Runs.tl, j.tl, h.tl, SummaryPC(Runs,h,j):0:5, SummaryPD(Runs,h,j):0:5, SummarySOC(Runs,h,j):0:5 /);
Putclose ;


FILE csvGen Report File /OutputGeneration.csv/;
PUT csvGen
put_utility 'ren' / '%outdir%\%case_name%\%sim_year%_OutputGeneration_SDOM_%FNAME%_Nuclear_' AlphaNuclear:0:0 '_Target_' GenMix_Target:00 '_Resilience_' %ResilienceOption%:00 '.csv';
csvGen.pc = 5;
PUT csvGen;

PUT 'Scenario', 'Hour','Solar PV Generation (MW)', 'Solar PV Curtailment (MW)', 'Wind Generation (MW)', 'Wind Curtailment (MW)', 'Gas CC Generation (MW)', 'Power from Storage and Gas CC to Storage (MW)', 'Imports (MW)', 'Exports (MW)', 'Hydropower (MW)' /;
loop ((Runs,h),
     PUT Runs.tl, h.tl, SolarPVGen(Runs,h):0:5, SolarPVCurt(Runs,h):0:5, WindGen(Runs,h):0:5, WindCurt(Runs,h):0:5, GenGasCC(Runs,h):0:5, StorageGasCC2Storage(Runs,h):0:5, ImportsPower(Runs,h):0:5, ExportsPower(Runs,h):0:5, HydroGene(Runs,h):0:5 /);
Putclose ;


FILE csvVRE Report File /OutputSelectedVRE.csv/;
PUT csvVRE
put_utility 'ren' / '%outdir%\%case_name%\%sim_year%_OutputSelectedVRE_SDOM_%FNAME%_Nuclear_' AlphaNuclear:0:0 '_Target_' GenMix_Target:00 '_Resilience_' %ResilienceOption%:00 '.csv';
csvVRE.pc = 5;
PUT csvVRE;

PUT 'Scenario', 'VRE unit ID', 'Technology', 'Selection ', 'latitude', 'longitude','Capacity (MW)'  /;
loop ((Runs,k),
     PUT Runs.tl, k.tl, 'Solar PV', SelectedSolarPV(Runs,k):0:5,CapSolar(k,'latitude'):0:5,CapSolar(k,'longitude'):0:5, CapSolar(k,'capacity'):0:5 /);

loop ((Runs,w),
     PUT Runs.tl, w.tl, 'Wind', SelectedWind(Runs,w):0:5,CapWind(w,'latitude'):0:5,CapWind(w,'longitude'):0:5, CapWind(w,'capacity'):0:5 /);
Putclose ;

* Export data to GDX
$GDXOUT SDOM_results.gdx
EXECUTE_UNLOAD;
 

*execute 'Consolidated_plots.py'


