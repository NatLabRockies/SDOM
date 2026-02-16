# -*- coding: utf-8 -*-
"""
Created on Wed Aug 27 23:15:21 2025

@author: amyers
"""

import pandas as pd
import seaborn as sns
import plotly.io as pio    

import plotly.graph_objects as go
from plotly.subplots import make_subplots

import numpy as np
import kaleido

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

import matplotlib.colors as mc 
from matplotlib.cm import ScalarMappable



class SDOMPlots:

    
    def __init__(self, csv_summary_files, csv_storage_files, renderer='browser'):
      
        pio.renderers.default = renderer
        
        # Load and combine all data
        self.df_all = self._load_summary_data(csv_summary_files)
        self.df_storage_all = self._load_storage_data(csv_storage_files)

# =============================================================================
# CONFIGURATION SECTION - EDIT TITLES HERE
# =============================================================================

        # Configuration dictionaries
        self.scenario_titles = {
#            '1': '2030 75% Target',
#            '2': '2030 90% Target',  
            '1': 'Location 3, Renewable Generation Mix = 0',
            '2': 'Location 3, Renewable Generation Mix = 1',
#            '3': '2035 100% Target',
#            '4': '2040 100% Target'
        }
        
        self.cost_breakdown_titles = {
            '1': 'Cost Analysis - Conservative Scenario',
            '2': 'Cost Analysis - Aggressive Renewable Push',
            '3': 'Cost Analysis - Full Decarbonization by 2035',
            '4': 'Cost Analysis - Extended Timeline Scenario'
        }
        
        # Color mapping for technologies
        self.color_map = {
            'Li-Ion': '#FF4A88',
            'CAES': '#FF4741', 
            'PHS': '#CC0079',
            'H2': '#FF7FBB',
            'GasCC': '#5E1688',
            'Solar PV': '#FFC903',  # Updated to match document 2       
            'Wind': '#00B6EF',      # Updated to match document 2             
            'Other renewables': '#32CD32',  
            'Hydro': '#187F94',            
            'Nuclear': '#820000',          
        }
        
        # Marker symbols for duration plot
        self.marker_symbols = {
            'Li-Ion': 'diamond',
            'LiIon': 'diamond',
            'CAES': 'circle',
            'PHS': 'square', 
            'H2': 'triangle-up',
            'GasCC': 'star',
            'VRB': 'hexagon'
        }
        
        # Storage technologies for cost analysis
        self.storage_technologies = ['LiIon', 'Li-Ion', 'CAES', 'PHS', 'H2']
        
        # Plot configuration
        self.plot_config = {
            'displayModeBar': False,
            'staticPlot': True,
            'doubleClick': False,
            'showTips': False,
            'showAxisDragHandles': False,
            'showAxisRangeEntryBoxes': False,
        }
        
    def _load_summary_data(self, summary_files):
        """Load and combine CSV files with scenario identifiers"""
        dfs = []
        for i, file in enumerate(summary_files, 1):
            df = pd.read_csv(file)
            df['File_Scenario'] = i
            df['Optimal Value'] = pd.to_numeric(df['Optimal Value'], errors='coerce')
            dfs.append(df)
        
        combined_df = pd.concat(dfs, ignore_index=True)
        print(f"Loaded {len(summary_files)} files with {len(combined_df)} total records")
        return combined_df
    
    def _load_storage_data(self, storage_files):
        """Load and combine CSV files with scenario identifiers"""
        dfs = []
        for i, file in enumerate(storage_files, 1):
            df = pd.read_csv(file)
            df['File_Scenario'] = i
            df['State of charge (MWh)'] = pd.to_numeric(df['State of charge (MWh)'], errors='coerce')
            dfs.append(df)
        
        combined_df = pd.concat(dfs, ignore_index=True)
        print(f"Loaded {len(storage_files)} files with {len(combined_df)} total records")
        return combined_df
    
# =============================================================================
# HELPER FUNCTIONS FOR FORMATTING
# =============================================================================
    def _convert_units_and_get_label(self, values, base_unit="MWh"):
        """Convert units based on maximum value and return appropriate label"""
        if not values:
            return values, base_unit
            
        max_val = max([abs(v) for v in values if v != 0])
        
        if base_unit == "MWh":
            if max_val > 10_000_000:
                return [v/1_000_000 for v in values], "TWh"
            elif max_val > 10_000:
                return [v/1_000 for v in values], "GWh"
            else:
                return values, "MWh"
        elif base_unit == "MW":
            if max_val > 10_000_000:
                return [v/1_000_000 for v in values], "TW"
            elif max_val > 10_000:
                return [v/1_000 for v in values], "GW"
            else:
                return values, "MW"
        else:
            return values, base_unit
    
    def _get_standard_layout(self):
        """Return standard layout settings for all plots"""
        return dict(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(
                showgrid=True,
                gridcolor='rgba(128,128,128,0.3)',
                zeroline=True,
                zerolinecolor='rgba(128,128,128,0.5)',
                zerolinewidth=1
            ),
            title=dict(x=0.5, xanchor='center', font=dict(size=16)),
            margin=dict(t=80)
        )
    
    def _filter_data_by_metric(self, metric, exclude_all=True, positive_only=False):
        """Filter data by metric with common preprocessing"""
        df_filtered = self.df_all[self.df_all['Metric'] == metric].copy()
        
        if exclude_all:
            df_filtered = df_filtered[df_filtered['Technology'] != 'All']
        
        df_filtered['Scenario'] = df_filtered['File_Scenario'].astype(str)
        df_filtered['Optimal Value'] = pd.to_numeric(df_filtered['Optimal Value'], errors='coerce').fillna(0)
        
        if positive_only:
            df_filtered = df_filtered[df_filtered['Optimal Value'] > 0]
        else:
            df_filtered = df_filtered[df_filtered['Optimal Value'] != 0]
            
        return df_filtered

    # =========================================================================
    # CAPACITY PER TECHNOLOGY
    # =========================================================================

    def create_matplotlib_doughnut_chart(self, scenario='1', figsize=(10, 10)):
        """Create matplotlib doughnut chart for capacity per technology"""
        
        # Filter data for the specified scenario
        scenario_data = self.df_all[self.df_all['File_Scenario'] == int(scenario)]
        
        # Get generation capacity data (exclude 'All')
        gen_capacity_data = scenario_data.loc[
            (scenario_data["Metric"] == "Capacity") & 
            (scenario_data["Technology"] != "All"), 
            ["Technology", "Optimal Value"]
        ]
        
        # Get storage capacity data (exclude 'All')
        sto_capacity_data = scenario_data.loc[
            (scenario_data["Metric"] == "Average power capacity") & 
            (scenario_data["Technology"] != "All"), 
            ["Technology", "Optimal Value"]
        ]
        
        # Combine capacity data
        capacity_n_labels = pd.concat([gen_capacity_data, sto_capacity_data], ignore_index=True)
        
        # Convert to numeric and filter out zero/negative values
        capacity_n_labels['Optimal Value'] = pd.to_numeric(capacity_n_labels['Optimal Value'], errors='coerce')
        capacity_filtered = capacity_n_labels[capacity_n_labels['Optimal Value'] > 0]
        
        # Calculate total capacity
        total_capacity = round(capacity_filtered['Optimal Value'].sum()/1000)  # Convert to GW
        
        if capacity_filtered.empty:
            print(f"No capacity data found for scenario {scenario}")
            return None
        
        # Get colors for technologies
        colors = [self.color_map.get(label, '#000000') for label in capacity_filtered['Technology']]
        
        # Create the doughnut chart
        fig, ax = plt.subplots(figsize=figsize)
        wedges, texts, autotexts = ax.pie(
            capacity_filtered['Optimal Value'], 
            startangle=90, 
            colors=colors, 
            autopct='%1.1f%%', 
            pctdistance=0.8,  
            textprops={'fontsize': 20, 'fontweight': 'bold', 'color': 'black'}
        )
        
        # Draw a circle at the center to create the donut effect
        centre_circle = plt.Circle((0, 0), 0.60, fc='white')
        fig.gca().add_artist(centre_circle)
        
        # Ensure the circle is a circle
        ax.axis('equal')
        
        # Add title and legend
        plt.title('Capacity per technology (MW)', y=0.95, fontsize=28)
        legend = plt.legend(
            capacity_filtered['Technology'], 
            bbox_to_anchor=(1.15, 0.9), 
            loc="upper right", 
            frameon=False, 
            fontsize=20, 
            labelcolor='black'
        )
        
        # Add center text
        centre_text = f'{total_capacity}GW'
        centre_text_line_2 = f'Total Capacity'
        ax.text(0, 0.1, centre_text, 
                horizontalalignment='center', 
                verticalalignment='center', 
                fontsize=32, fontweight='bold',
                color='black')
        ax.text(0, -0.1, centre_text_line_2, 
                horizontalalignment='center', 
                verticalalignment='center', 
                fontsize=30, fontweight='bold',
                color='black')
        
        plt.tight_layout()
        
        # Save the plot
        filename = f'Capacity_per_tech_scenario_{scenario}.png'
        plt.savefig(filename, dpi=1000, bbox_inches='tight')
        plt.show()
        
        print(f"Doughnut chart saved as {filename}")
        return fig
# =============================================================================
# HEAT MAP PLOTS
# =============================================================================

    def create_storage_heatmap(self, scenario='1', technology='H2', figsize=(12, 10)):
        """Create heatmap for storage state of charge (from document 2)"""
        
        # Filter data for the specified scenario and technology
        scenario_data = self.df_storage_all[self.df_storage_all['File_Scenario'] == int(scenario)]
        
        # Get state of charge data for the specified technology
#        scenario_data = pd.read_csv("OutputStorage_SDOM_SDOM_pyomo_cbc_122324_Nuclear_1_Target_1.00_.csv")
        soc_data = scenario_data.loc[
            scenario_data["Technology"] == technology, 
            "State of charge (MWh)"
        ]
        
        if soc_data.empty:
            print(f"No state of charge data found for {technology} in scenario {scenario}")
            return None
        
        # Create hours array (assuming 8760 hours in a year)
        hours = np.arange(1, 8761)
        
        # Create DataFrame with hours
        df = pd.DataFrame(data=hours, columns=["Hour of the Year"])
        
        # Create datetime index
        start_date = '2023-01-01 00:00:00'
        datetime_index = pd.date_range(start=start_date, periods=8760, freq='H')
        df['timestamp'] = datetime_index
        
        # Extract day of year and hour of day
        df['day_of_year'] = df['timestamp'].dt.dayofyear
        df['hour_of_day'] = df['timestamp'].dt.hour
        
        # Reshape SOC values for heatmap (24 hours x 365 days)
        try:
            SOC = soc_data.values.reshape(24, len(df['day_of_year'].unique()), order="F")
            norm_SOC = SOC * 100 / np.max(SOC)  # Normalize to percentage
        except ValueError:
            print(f"Error reshaping SOC data for {technology}. Data length: {len(soc_data)}")
            return None
        
        # Create grids for plotting
        xgrid = np.arange(df['day_of_year'].max() + 1) + 1
        ygrid = np.arange(25)
        
        # Create the heatmap
        fig, ax = plt.subplots(figsize=figsize)
        
        # Custom colormap (from document 2)
        CB_color_cycle = [
            '#00296b', '#003f88', '#00509d', '#1F449C', 
            '#ffd500', '#fdc500', '#F05039'                             
        ]
        custom_cmap = LinearSegmentedColormap.from_list("my_cmap", CB_color_cycle)
        
        # Create heatmap
        heatmap = ax.pcolormesh(xgrid, ygrid, norm_SOC, cmap=custom_cmap)
        
        # Formatting
        ax.set_xticklabels(ax.get_xmajorticklabels(), fontsize=16) 
        ax.set_yticklabels(ax.get_ymajorticklabels(), fontsize=16)
        ax.set_frame_on(False)  # Remove all spines
        
        # Set limits and add colorbar
        plt.xlim(0, 365)  
        plt.ylim(0, 24)
        plt.colorbar(heatmap, label='State of Charge (%)')
        
        # Labels and title
        plt.xlabel("Day of the year", fontsize=20)
        plt.ylabel("Hour of the day", fontsize=20)
        plt.title(f"Annual Hourly {technology} Storage State of Charge (%)", 
                 y=1.05, fontsize=20)
        
        # Save the plot
        filename = f'SOC_{technology}_scenario_{scenario}.png'
        plt.savefig(filename, dpi=1000, bbox_inches='tight')
        plt.show()
        
        print(f"Heatmap saved as {filename}")
        return fig

    # =========================================================================
    # STORAGE CAPACITY PER TECHNOLOGY PER SCENARIO 
    # =========================================================================

    def create_storage_capacity_plot(self, 
                                   title="Storage Capacity Per Technology vs Scenario",
                                   title_y_position=0.90,
                                   x_axis_font_size=16,
                                   y_axis_font_size=16,
                                   legend_font_size=14,
                                   height=800,
                                   width=750,
                                   filename="storage_plot_overlay.html"):
        """Create storage capacity overlay plot"""
        
        # Get storage capacity data
        df_metric = self._filter_data_by_metric("Average power capacity")
        scenarios = sorted(df_metric['Scenario'].unique())
        technologies = df_metric['Technology'].unique()
        
        # Collect values for unit conversion
        all_values = []
        for tech in technologies:
            tech_data = df_metric[df_metric['Technology'] == tech]
            all_values.extend(tech_data['Optimal Value'].tolist())
        
        # Convert units
        converted_values, unit_label = self._convert_units_and_get_label(all_values, "MW")
        conversion_factor = converted_values[0] / all_values[0] if all_values and all_values[0] != 0 else 1
        
        # Sort technologies by maximum value
        tech_max_values = {tech: df_metric[df_metric['Technology'] == tech]['Optimal Value'].max() 
                          for tech in technologies}
        technologies_sorted = sorted(technologies, key=lambda x: tech_max_values[x], reverse=True)
        
        # Create figure
        fig = go.Figure()
        
        # Add traces for each technology
        use_transparency = len(technologies_sorted) > 1
        opacity_value = 0.8 if use_transparency else 1.0
        
        for tech in technologies_sorted:
            tech_data = df_metric[df_metric['Technology'] == tech]
            
            x_vals = []
            y_vals = []
            
            for scenario in scenarios:
                scenario_tech_data = tech_data[tech_data['Scenario'] == scenario]
                x_vals.append(self.scenario_titles.get(scenario, f"Scenario {scenario}"))
                
                if not scenario_tech_data.empty:
                    original_val = scenario_tech_data['Optimal Value'].iloc[0]
                    y_vals.append(original_val * conversion_factor)
                else:
                    y_vals.append(0)
            
            fig.add_trace(
                go.Bar(
                    x=x_vals,
                    y=y_vals,
                    name=tech,
                    marker_color=self.color_map.get(tech, '#000000'),
                    opacity=opacity_value,
                    text=[f"{v:.1f}" if v != 0 else "" for v in y_vals],
                    textposition='inside',
                    textfont=dict(color='black', size=1, family='Arial Black'),
                    hovertemplate='<extra></extra>',
                    showlegend=True
                )
            )
        
        # Update layout
        layout_settings = self._get_standard_layout()
        layout_settings.update({
            'title': {
                'text': title,
                'x': 0.5,
                'xanchor': 'center',
                'y': title_y_position,
                'yanchor': 'top',
                'font': dict(size=18, color='black')
            },
            'xaxis': {
                'title': 'Scenario',
                'showgrid': False,
                'zeroline': False,
                'tickfont': dict(size=12, color='black'),
                'title_standoff': 15,
                'title_font': dict(color='black', size=x_axis_font_size),
            },
            'yaxis': {
                'title': f'Average storage Power Capacity ({unit_label})',
                'showgrid': True,
                'gridcolor': 'rgba(128,128,128,0.3)',
                'zeroline': True,
                'zerolinecolor': 'rgba(128,128,128,0.5)',
                'zerolinewidth': 1,
                'tickfont': dict(color='black'),
                'title_font': dict(color='black', size=y_axis_font_size)
            },
            'barmode': 'overlay',
            'height': height,
            'width': width,
            'legend': {
                'traceorder': 'normal',
                'font': dict(color='black', size=legend_font_size),
                'itemwidth': 40,
                'bordercolor': 'rgba(255,255,255,0)',
                'borderwidth': 0,
                'bgcolor': 'rgba(255,255,255,0)',
            },
            'margin': dict(t=80, b=100)
        })
        
        fig.update_layout(**layout_settings)
        fig.write_html(filename, auto_open=True, config=self.plot_config)
        filename = f'Storage_Power_Capacity_{scenario}.png'
        plt.savefig(filename, dpi=1000, bbox_inches='tight')
        plt.show()
        print(f"Created storage capacity plot: {filename}")
        
        return fig
    
    # =========================================================================
    # STORAGE DURATION PER TECHNOLOGY VS SCENARIO 
    # =========================================================================

    def create_storage_duration_plot(self, 
                                   title="Duration Per Technology vs Scenario",
                                   title_y_position=0.92,
                                   main_title_size=18,
                                   axis_title_size=16,
                                   legend_title_size=12,
                                   legend_text_size=12,
                                   height=600,
                                   width=700,
                                   filename="duration_plot_markers.html"):
        """Create storage duration scatter plot with markers"""
        
        # Get duration data
        df_duration = self._filter_data_by_metric("Discharge duration", exclude_all=True, positive_only=False)
        
        if df_duration.empty:
            print("No duration data found")
            return None
        
        # Get unique technologies and scenarios for duration
        technologies_duration = df_duration['Technology'].unique()
        scenarios_duration = sorted(df_duration['Scenario'].unique())
        
        # Sort technologies by maximum duration value
        tech_max_duration = {}
        for tech in technologies_duration:
            tech_data = df_duration[df_duration['Technology'] == tech]
            max_val = tech_data['Optimal Value'].max()
            tech_max_duration[tech] = max_val
        
        technologies_duration_sorted = sorted(technologies_duration, key=lambda x: tech_max_duration[x], reverse=True)
        
        # Create figure
        fig = go.Figure()
        
        # Add a trace for each technology (largest first)
        for tech in technologies_duration_sorted:
            tech_data = df_duration[df_duration['Technology'] == tech]
            
            x_vals = []
            y_vals = []
            text_vals = []
            
            for scenario in scenarios_duration:
                scenario_tech_data = tech_data[tech_data['Scenario'] == scenario]
                if not scenario_tech_data.empty:
                    x_vals.append(self.scenario_titles.get(scenario, f"Scenario {scenario}"))
                    y_vals.append(scenario_tech_data['Optimal Value'].iloc[0])
                    text_vals.append(str(round(scenario_tech_data['Optimal Value'].iloc[0], 1)))
            
            # Only add trace if there's data to plot
            if x_vals and y_vals:
                fig.add_trace(
                    go.Scatter(
                        x=x_vals,
                        y=y_vals,
                        mode='markers+text',
                        name=tech,
                        marker=dict(
                            color=self.color_map.get(tech, '#000000'),
                            size=12,
                            symbol=self.marker_symbols.get(tech, 'circle'),
                            line=dict(width=1, color='black')  # Add black outline to markers
                        ),
                        text=text_vals,
                        textposition='top center',
                        textfont=dict(color='black', size=12, family='Arial Black'),
                        hovertemplate='<extra></extra>'  # Remove hover info
                    )
                )
        
        # Update layout for scatter plot
        layout_settings = self._get_standard_layout()
        layout_settings.update({
            'title': {
                'text': title,
                'x': 0.5,
                'xanchor': 'center',
                'y': title_y_position,
                'yanchor': 'top',
                'font': dict(color='black', size=main_title_size)
            },
            'xaxis': dict(
                title='Scenario',
                showgrid=False,
                linecolor='black',
                linewidth=1,
                mirror=True,
                title_font=dict(color='black', size=axis_title_size),
                tickfont=dict(color='black')
            ),
            'yaxis': dict(
                title='Duration (h)',
                range=[0, max(df_duration['Optimal Value']) * 1.1] if not df_duration.empty else [0, 10],
                showgrid=False,
                linecolor='black',
                linewidth=1,
                mirror=True,
                title_font=dict(color='black', size=axis_title_size),
                tickfont=dict(color='black')
            ),
            'height': height,
            'width': width,
            'plot_bgcolor': 'white',
            'paper_bgcolor': 'white',
            'showlegend': True,
            'legend': dict(
                font=dict(color='black', size=legend_text_size),
                title=dict(font=dict(color='black', size=legend_title_size))
            ),
            'font': dict(color='black')
        })
        
        fig.update_layout(**layout_settings)
        fig.write_html(filename, auto_open=True, config=self.plot_config)
        filename = f'Duration_per_technology_{scenario}.png'
        plt.savefig(filename, dpi=1000, bbox_inches='tight')
        plt.show()
        print(f"Created duration plot: {filename}")
        
        return fig
    
    # =========================================================================
    # TOTAL GENERATION BREAKDOWN AND DEMAND
    # =========================================================================
    
    def create_scenario_donut_plots(self, height=1000, width=950):
        """Create individual donut chart plots for each scenario"""
        
        # Get data for all three metrics
        df_generation = self._filter_data_by_metric("Total generation", positive_only=True)
        df_charging = self._filter_data_by_metric("Storage energy charging", positive_only=True)
        df_demand = self._filter_data_by_metric("Total demand", exclude_all=False)
        
        # Convert units for consistency
        all_values = (df_generation['Optimal Value'].tolist() + 
                     df_demand['Optimal Value'].tolist() + 
                     df_charging['Optimal Value'].tolist())
        
        _, gen_unit = self._convert_units_and_get_label(all_values, "MWh")
        if gen_unit == "TWh":
            conversion_factor = 1/1_000_000
        elif gen_unit == "GWh":
            conversion_factor = 1/1_000
        else:
            conversion_factor = 1
        
        scenarios = sorted(df_generation['Scenario'].unique())
        
        # Create plot for each scenario
        for scenario in scenarios:
            scenario_title = self.scenario_titles.get(scenario, f"Scenario {scenario}")
            
            # Create subplot figure with increased vertical spacing
            fig = make_subplots(
                rows=2, cols=1,
                row_heights=[0.45, 0.55],
                specs=[[{"type": "pie"}], [{"type": "xy"}]],
                subplot_titles=["<b>Generation Technology Mix</b>", "<b>Generation vs Demand</b>"],  # Change 2: Bold text
                vertical_spacing=0.18  # Change 1: Increased space between donut chart and title
            )
            
            # Get scenario-specific data
            scenario_gen_data = df_generation[df_generation['Scenario'] == scenario]
            scenario_demand_data = df_demand[df_demand['Scenario'] == scenario]
            scenario_charging_data = df_charging[df_charging['Scenario'] == scenario]
            
            # Calculate totals
            total_generation = scenario_gen_data['Optimal Value'].sum() * conversion_factor
            total_charging = scenario_charging_data['Optimal Value'].sum() * conversion_factor
            demand_val = (scenario_demand_data['Optimal Value'].iloc[0] * conversion_factor 
                         if not scenario_demand_data.empty else 0)
            
            # Add donut chart
            if not scenario_gen_data.empty:
                labels = scenario_gen_data['Technology'].tolist()
                values = (scenario_gen_data['Optimal Value'] * conversion_factor).tolist()
                colors = [self.color_map.get(tech, '#000000') for tech in labels]
                
                fig.add_trace(
                    go.Pie(
                        labels=labels,
                        values=values,
                        hole=0.5,
                        marker=dict(colors=colors, line=dict(color='white', width=2)),
                        textinfo='percent',
                        texttemplate='%{percent:.1%}',
                        textposition='auto',
                        textfont=dict(size=12, color='white', family='Arial Black'),
                        outsidetextfont=dict(size=12, color='black', family='Arial Black'),
                        insidetextorientation='radial',
                        showlegend=True,
                        legendgroup="pie",
                        hoverinfo='none',
                    ),
                    row=1, col=1
                )
                
                # Add center text
                fig.add_annotation(
                    text=f"<b>{total_generation:.0f}{gen_unit}</b><br><span style='font-size:12px; color:black'>Total Generation</span>",
                    x=0.5, y=0.845,
                    xref="paper", yref="paper",
                    showarrow=False,
                    font=dict(size=16, color="black", family="Arial Black"),
                    align="center"
                )
            
            # Add proportional bar chart
            bar_width = 0.4
            max_value = max(total_generation, demand_val) * 2.5
            
           
            fig.add_trace(
                go.Bar(
                    x=['Energy Balance'],  
                    y=[total_generation],
                    name='Gross Generation',
                    marker_color='steelblue',
                    text=[f"{total_generation:.1f}"],
                    textposition='inside',
                    textfont=dict(size=14, color='white', family='Arial Black'),
                    hoverinfo='none',
                    showlegend=True,
                    legendgroup="bar",
                    width=bar_width,
                    offset=-0.25  # Move left to create space from demand bar
                ),
                row=2, col=1
            )
            
            # Storage charging bar (if applicable)
            if total_charging > 0:
                fig.add_trace(
                    go.Bar(
                        x=['Energy Balance'],
                        y=[-total_charging],
                        name='Storage Charging',
                        marker_color='orange',
                        text=[f"-{total_charging:.1f}"],
                        textposition='inside',
                        textfont=dict(size=14, color='white', family='Arial Black'),
                        hoverinfo='none',
                        showlegend=True,
                        legendgroup="bar",
                        width=bar_width,
                        offset=-0.25  # Keep same position as gross generation
                    ),
                    row=2, col=1
                )
            
       
            fig.add_trace(
                go.Bar(
                    x=['Demand'],
                    y=[demand_val],
                    name='Demand',
                    marker_color='red',
                    text=[f"{demand_val:.1f}"],
                    textposition='inside',
                    textfont=dict(size=14, color='white', family='Arial Black'),
                    hoverinfo='none',
                    showlegend=True,
                    legendgroup="bar",
                    width=bar_width,
                    offset=-0.5  # Move closer to energy balance bars
                ),
                row=2, col=1
            )
            
            # Update layout
            fig.update_layout(
                title=dict(
                    text=scenario_title,
                    x=0.5,
                    xanchor='center',
                    font=dict(size=18, color='black')
                ),
                height=height,
                width=width,
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='white',
                margin=dict(t=120, b=100, l=120, r=100),
                font=dict(family='Arial, sans-serif', size=12, color='black'),
                barmode='relative',
                # Change 3: Move Technologies legend closer to donut chart center
                legend=dict(
                    itemsizing='constant',
                    itemwidth=40,
                    font=dict(size=11, color='black'),
                    bordercolor='rgba(0,0,0,0)',
                    borderwidth=0,
                    x=0.75,  # Moved more center from 0.98
                    y=0.75,  # Moved closer to donut chart from 0.85
                    title=dict(text="Technologies", font=dict(size=12, color='black'))
                ),
                # Energy Balance Legend
                legend2=dict(
                    itemsizing='constant',
                    itemwidth=40,
                    font=dict(size=11, color='black'),
                    bordercolor='rgba(0,0,0,0)',
                    borderwidth=0,
                    x=1.05,  
                    y=0.25,  # Adjusted vertical position
                    title=dict(text="Energy Balance", font=dict(size=12, color='black'))
                )
            )
            
            # Assign bar chart traces to second legend
            for trace in fig.data:
                if hasattr(trace, 'legendgroup') and trace.legendgroup == "bar":
                    trace.update(legend="legend2")
            
            # Update axes
            fig.update_yaxes(
                title_text=f"Energy ({gen_unit})",
                showgrid=True,
                gridcolor='rgba(128,128,128,0.3)',
                title_font=dict(size=14, color='black'),
                tickfont=dict(size=12, color='black'),
                range=[-max_value*0.2, max_value],
                zeroline=True,
                zerolinecolor='black',
                zerolinewidth=1,
                row=2, col=1
            )
            
            fig.update_xaxes(
                title_text="",
                tickfont=dict(size=14, color='black'),
                showgrid=False,
                zeroline=False,
                row=2, col=1
            )
            
            # Save plot
            filename = f"scenario_{scenario}_donut_proportional_bars.html"
            fig.write_html(filename, auto_open=True, config=self.plot_config, include_plotlyjs='cdn')
            print(f"Created donut plot for {scenario_title}: {filename}")

    # =========================================================================
    # CAPEX AND OPEX PER TECHNOLOGY
    # =========================================================================

    def create_storage_cost_breakdown_plots(self, 
                                          bar_width=0.3,
                                          title_y_position=0.90,
                                          title_size=18,
                                          axis_title_size=16,
                                          tick_label_size=14,
                                          legend_title_size=14,
                                          legend_text_size=14,
                                          height=600,
                                          width=700):
        """Create CAPEX/OPEX cost breakdown plots for storage technologies"""
        
        # Filter for cost metrics
        df_total_capex = self._filter_data_by_metric("Total CAPEX", exclude_all=False, positive_only=False)
        df_opex = self._filter_data_by_metric("OPEX", exclude_all=False, positive_only=False)
        df_capex = self._filter_data_by_metric("CAPEX", exclude_all=False, positive_only=False)
        
        # Filter for storage technologies only
        df_total_capex = df_total_capex[df_total_capex['Technology'].isin(self.storage_technologies)]
        df_opex = df_opex[df_opex['Technology'].isin(self.storage_technologies)]
        df_capex = df_capex[df_capex['Technology'].isin(self.storage_technologies)]
        
        # Get scenarios with cost data
        scenarios_cost = sorted(set(df_total_capex['Scenario'].unique()) | 
                               set(df_opex['Scenario'].unique()) | 
                               set(df_capex['Scenario'].unique()))
        
        print(f"Scenarios with storage technology cost data: {scenarios_cost}")
        
        # Colors for different cost types
        capex_color = '#000080'  # Blue
        opex_color = '#FF8C00'   # Orange
        
        # Create separate plots for each scenario
        for scenario in scenarios_cost:
            df_total_capex_scenario = df_total_capex[df_total_capex['Scenario'] == scenario]
            df_opex_scenario = df_opex[df_opex['Scenario'] == scenario]
            df_capex_scenario = df_capex[df_capex['Scenario'] == scenario]
            
            # Get storage technologies that have any cost data in this scenario
            technologies_scenario = (set(df_total_capex_scenario['Technology'].unique()) | 
                                   set(df_opex_scenario['Technology'].unique()) |
                                   set(df_capex_scenario['Technology'].unique()))
            
            # Filter to only include our defined storage technologies
            technologies_scenario = technologies_scenario.intersection(set(self.storage_technologies))
            
            if not technologies_scenario:
                print(f"No storage technology cost data found for Scenario {scenario}")
                continue
            
            # Create figure for this scenario
            fig_cost = go.Figure()
            
            # Track which technologies have data to plot
            techs_with_data = []
            
            # Collect data for all technologies in this scenario
            cost_data = []
            
            # Add traces for each storage technology
            for tech in sorted(technologies_scenario):
                # Get Total CAPEX value for this technology
                total_capex_data = df_total_capex_scenario[df_total_capex_scenario['Technology'] == tech]
                if not total_capex_data.empty:
                    total_capex_raw = total_capex_data['Optimal Value'].iloc[0]
                    if pd.isna(total_capex_raw) or str(total_capex_raw).strip() == '-':
                        total_capex_value = 0.0
                    else:
                        total_capex_value = float(total_capex_raw)
                else:
                    total_capex_value = 0.0
                
                # Get OPEX value for this technology  
                opex_data = df_opex_scenario[df_opex_scenario['Technology'] == tech]
                if not opex_data.empty:
                    opex_raw = opex_data['Optimal Value'].iloc[0]
                    if pd.isna(opex_raw) or str(opex_raw).strip() == '-':
                        opex_value = 0.0
                    else:
                        opex_value = float(opex_raw)
                else:
                    opex_value = 0.0
                
                # Get CAPEX value for this technology
                capex_data = df_capex_scenario[df_capex_scenario['Technology'] == tech]
                if not capex_data.empty:
                    capex_raw = capex_data['Optimal Value'].iloc[0]
                    if pd.isna(capex_raw) or str(capex_raw).strip() == '-':
                        capex_value = 0.0
                    else:
                        capex_value = float(capex_raw)
                else:
                    capex_value = 0.0
                
                # Use Total CAPEX if available, otherwise use CAPEX
                capex_to_plot = total_capex_value if total_capex_value > 0 else capex_value
                
                # Only collect data if there's something to plot
                if capex_to_plot > 0 or opex_value > 0:
                    techs_with_data.append(tech)
                    cost_data.append({
                        'Technology': tech,
                        'CAPEX': capex_to_plot,
                        'OPEX': opex_value
                    })
            
            if not cost_data:
                print(f"No cost data to plot for Scenario {scenario}")
                continue
            
            # Create overlaid bars showing larger value in background, smaller on top
            technologies = [item['Technology'] for item in cost_data]
            capex_values = [item['CAPEX'] for item in cost_data]
            opex_values = [item['OPEX'] for item in cost_data]
            
            # Calculate larger and smaller values for overlay effect
            larger_values = []
            smaller_values = []
            larger_colors = []
            smaller_colors = []
            
            for i, tech in enumerate(technologies):
                capex = capex_values[i]
                opex = opex_values[i]
                
                if capex >= opex:
                    larger_values.append(capex)
                    smaller_values.append(opex)
                    larger_colors.append(capex_color)
                    smaller_colors.append(opex_color)
                else:
                    larger_values.append(opex)
                    smaller_values.append(capex)
                    larger_colors.append(opex_color)
                    smaller_colors.append(capex_color)
            
            # Add larger values trace (background)
            if any(val > 0 for val in larger_values):
                fig_cost.add_trace(
                    go.Bar(
                        x=technologies,
                        y=larger_values,
                        name='Larger Values',
                        marker_color=larger_colors,
                        showlegend=False,
                        width=bar_width
                    )
                )
            
            # Add smaller values trace (foreground)
            if any(val > 0 for val in smaller_values):
                fig_cost.add_trace(
                    go.Bar(
                        x=technologies,
                        y=smaller_values,
                        name='Smaller Values',
                        marker_color=smaller_colors,
                        showlegend=False,
                        width=bar_width
                    )
                )
            
            # Add proper legend traces
            fig_cost.add_trace(
                go.Bar(
                    x=[None], y=[None], name='CAPEX', marker_color=capex_color, 
                    showlegend=True, width=bar_width
                )
            )
            fig_cost.add_trace(
                go.Bar(
                    x=[None], y=[None], name='OPEX', marker_color=opex_color, 
                    showlegend=True, width=bar_width
                )
            )
            
           
            scenario_title = self.cost_breakdown_titles.get(scenario, f'Storage Technologies Cost Breakdown - Scenario {scenario}')
            
            fig_cost.update_layout(
                title=dict(
                    text=scenario_title,
                    x=0.5,
                    xanchor='center',
                    y=title_y_position,
                    font=dict(size=title_size, color='black')
                ),
                xaxis=dict(
                    title=dict(
                        text='Storage Technology',
                        font=dict(size=axis_title_size, color='black')
                    ),
                    tickangle=0,
                    tickfont=dict(size=tick_label_size, color='black'),
                    categoryorder='array',
                    categoryarray=sorted(techs_with_data),
                    linecolor='white',
                    linewidth=0,
                    mirror=False
                ),
                yaxis=dict(
                    title=dict(
                        text='Cost ($)',
                        font=dict(size=axis_title_size, color='black')
                    ),
                    tickfont=dict(size=tick_label_size, color='black'),
                    showgrid=True,
                    gridcolor='lightgray',
                    gridwidth=1,
                    zeroline=True,
                    zerolinecolor='lightgray',
                    zerolinewidth=1,
                    linecolor='white',
                    linewidth=0,
                    mirror=False
                ),
                legend=dict(
                    title=dict(text='', font=dict(size=legend_title_size, color='black')),
                    font=dict(size=legend_text_size, color='black')
                ),
                barmode='overlay',
                height=height,
                width=width,
                plot_bgcolor='white',
                paper_bgcolor='white',
                font=dict(color='black')
            )
            
            # Save each scenario as separate HTML file
            filename = f"storage_cost_breakdown_scenario_{scenario}.html"
            fig_cost.write_html(filename, auto_open=True, config=self.plot_config)
            
            print(f"Storage technologies cost breakdown plot for Scenario {scenario} created: {filename}")
            print(f"Technologies plotted: {techs_with_data}")
        
        return True

    # =========================================================================
    # MASTER FUNCTION FOR CREATING ALL PLOTS
    # =========================================================================

    def create_all_plots(self):
        """Convenience method to create all plot types"""
        
        print("=" * 60)
        print("CREATING ALL SDOM PLOTS")
        print("=" * 60)
        
        print("\n1. Creating storage capacity plots...")
        self.create_storage_capacity_plot()
        
        print("\n2. Creating storage duration plots...")
        self.create_storage_duration_plot()
        
        print("\n3. Creating scenario donut plots...")
        self.create_scenario_donut_plots()
        
        print("\n4. Creating storage cost breakdown plots...")
        self.create_storage_cost_breakdown_plots()
        
        # Create matplotlib plots for all scenarios
        scenarios = ['1', '2', '3', '4']
        
        print("\n5. Creating matplotlib doughnut charts...")
        for scenario in scenarios:
            print(f"   - Creating doughnut chart for scenario {scenario}...")
            self.create_matplotlib_doughnut_chart(scenario=scenario)
        
        print("\n6. Creating storage heatmaps...")
        # Create heatmaps for Li-Ion storage in all scenarios
        storage_techs = ['Li-Ion']  # Try both naming conventions
        for scenario in scenarios:
            print(f"   - Creating heatmap for scenario {scenario}...")
            for tech in storage_techs:
                try:
                    self.create_storage_heatmap(scenario=scenario, technology=tech)
                    break  # If one works, don't try the other
                except Exception as e:
                    print(f"     Could not create heatmap for {tech} in scenario {scenario}: {e}")
                    continue
        
        print("\n" + "=" * 60)
        print("ALL PLOTS CREATED SUCCESSFULLY!")
        print("=" * 60)


# ============================================================================= 
# MAIN EXECUTION SECTION
# =============================================================================

def main():
    """Main function to demonstrate all plotting capabilities"""
    
    # Define your CSV files
    summary_files = [
        "OutputSummary_SDOM_MEA_Nuclear_1_Target_0.00_.csv",
        "OutputSummary_SDOM_MEA_Nuclear_1_Target_1.00_.csv", 
#        "OutputSummary_SDOM_SDOM_pyomo_cbc_122324_Nuclear_1_Target_1.00_.csv",
#        "OutputSummary_SDOM_SDOM_pyomo_cbc_122324_Nuclear_1_Target_1.00_.csv"       
    ]
    
    storage_files = [
        "OutputStorage_SDOM_MEA_Nuclear_1_Target_0.00_.csv",
        "OutputStorage_SDOM_MEA_Nuclear_1_Target_1.00_.csv", 
#        "OutputStorage_SDOM_SDOM_pyomo_cbc_122324_Nuclear_1_Target_1.00_.csv",
#        "OutputStorage_SDOM_SDOM_pyomo_cbc_122324_Nuclear_1_Target_1.00_.csv"       
    ]
    

    # Create analyzer instance
    analyzer = SDOMPlots(summary_files, storage_files, renderer='browser')
    
    analyzer.create_all_plots()
    
   

if __name__ == "__main__":
    main()