from pyomo.environ import value
import pandas as pd
import os
import logging

_NO_VALUE = object()


def safe_pyomo_value(var):
    """Safely extract the value from a Pyomo variable or expression.
    
    This function attempts to retrieve the value of a Pyomo variable or expression
    after optimization. It handles cases where the variable may be uninitialized or None.
    
    Args:
        var: A Pyomo variable, expression, or parameter from which to extract the value.
            Can be None.
    
    Returns:
        The numeric value of the variable/expression if it is initialized and not None,
        otherwise returns None.
    
    Notes:
        This function is essential when collecting results from solved models, as it
        prevents ValueErrors when accessing uninitialized or optional model components.
    """
    if var is None:
        return None

    # Fast path for VarData / ParamData where .value is already materialized.
    direct_value = getattr(var, "value", _NO_VALUE)
    if direct_value is not _NO_VALUE and not callable(direct_value):
        return direct_value

    try:
        return value(var)
    except (ValueError, TypeError):
        return None
    
    
def normalize_string(name:str) -> str:
    """Normalize a string for case-insensitive filename comparison.
    
    Removes spaces, hyphens, and underscores from the input string and converts
    it to lowercase. This function is used to match CSV filenames flexibly,
    ignoring common formatting variations.
    
    Args:
        name (str): The string to normalize (typically a filename or identifier).
    
    Returns:
        str: The normalized string with spaces, hyphens, and underscores removed,
             converted to lowercase.
    
    Example:
        >>> normalize_string("Load_hourly-2025.csv")
        'loadhourly2025.csv'
    """
    return name.replace(' ', '').replace('-', '').replace('_', '').lower()

def get_complete_path(filepath, file_name):
    """Search for a CSV file in a directory using flexible name matching.
    
    This function performs case-insensitive matching of CSV filenames, ignoring
    spaces, hyphens, and underscores. It searches the specified directory for a
    file that matches the base_name pattern.
    
    Args:
        filepath (str): Directory path where the file should be located.
        file_name (str): Base filename to search for (should include .csv extension).
    
    Returns:
        str: Complete path to the matched file if found, otherwise an empty string.
    
    Notes:
        Only searches for files with .csv extension. Uses normalize_string() for
        flexible matching to handle variations in input file naming conventions.
    """

    base_name, ext = os.path.splitext(file_name)
    if ext.lower() == '.csv':
        for f in os.listdir(filepath):
            normalized_f = normalize_string(f.split('.csv')[0])
            if normalized_f.startswith( normalize_string( base_name) ) and f.lower().endswith('.csv'):
                logging.debug(f"Found matching file: {f}")
                return os.path.join(filepath, f)
    
    return ""

def check_file_exists(filepath, file_name, file_description = ""):
    """Verify that a required input file exists in the specified directory.
    
    This function searches for a file using flexible name matching via get_complete_path()
    and raises an informative error if the file is not found.
    
    Args:
        filepath (str): Directory path where the file should be located.
        file_name (str): Filename to search for (typically a CSV file).
        file_description (str, optional): Human-readable description of the file's
            purpose, used in error messages. Defaults to empty string.
    
    Returns:
        str: Complete path to the verified file.
    
    Raises:
        FileNotFoundError: If the specified file cannot be found in the directory,
            with an error message including the file description.
    
    Notes:
        This function logs an error message before raising the exception to help
        with debugging input data configuration issues.
    """
    
    input_file_path = get_complete_path(filepath, file_name)#os.path.join(filepath, file_name)

    if not os.path.isfile(input_file_path):
        logging.error(f"Expected {file_description} file not found: {filepath}{file_name}")
        raise FileNotFoundError(f"Expected {file_description} file not found: {filepath}{file_name}")

    return input_file_path

def compare_lists(list1, list2, text_comp='', list_names=['','']):
    """Compare two lists for consistency in length and elements.
    
    Validates that two lists have the same length and contain the same elements,
    logging warnings for any discrepancies. Used to verify consistency between
    related datasets (e.g., capacity factors vs. CAPEX data for the same plants).
    
    Args:
        list1 (list): First list to compare.
        list2 (list): Second list to compare.
        text_comp (str, optional): Description of what is being compared, used in
            warning messages. Defaults to empty string.
        list_names (list of str, optional): Two-element list containing names/labels
            for the lists being compared (e.g., ['CF', 'Capex']). Defaults to ['', ''].
    
    Returns:
        bool: True if lists have the same length and elements, False otherwise.
    
    Notes:
        Uses set comparison to check for element equality, so order is ignored.
        Logs warnings via logging module when discrepancies are found.
    """
    if len(list1) != len(list2):
        logging.warning(f"Lists {text_comp} have different lengths ({list_names[0]} vs {list_names[1]}): {len(list1)} vs {len(list2)}")
        return False
    if set(list1) != set(list2):
        logging.warning(f"Lists {text_comp} have different elements ({list_names[0]} vs {list_names[1]}): {set(list1)} vs {set(list2)}")
        return False
    return True

def concatenate_dataframes( df: pd.DataFrame, 
                           new_data_dict: dict, 
                           run = 1,
                           unit = '$US',
                           metric = ''
                        ):
    """Append optimization results from a dictionary to an existing DataFrame.
    
    This function converts a dictionary of results into a DataFrame row and appends
    it to the existing DataFrame with additional metadata columns (Run, Unit, Metric).
    Used for collecting results across multiple optimization runs or scenarios.
    
    Args:
        df (pd.DataFrame): The DataFrame to which the new data will be appended.
        new_data_dict (dict): Dictionary containing technology names as keys and
            optimal values as values (e.g., {'Li-Ion': 1250.5, 'CAES': 800.0}).
        run (int, optional): Run or scenario identifier. Defaults to 1.
        unit (str, optional): Unit of measurement for the values. Defaults to '$US'.
        metric (str, optional): Metric name or description (e.g., 'Capacity', 'Cost').
            Defaults to empty string.
    
    Returns:
        pd.DataFrame: Updated DataFrame with the new row(s) appended, containing
            columns: ['Technology', 'Optimal Value', 'Run', 'Unit', 'Metric'].
    
    Notes:
        The new_data_dict is pivoted so each key becomes a separate row in the
        resulting DataFrame, all sharing the same Run, Unit, and Metric values.
    """
    new_df = pd.DataFrame.from_dict(new_data_dict, orient='index',columns=['Optimal Value'])
    new_df = new_df.reset_index(names=['Technology'])
    new_df['Run'] = run
    new_df['Unit'] = unit
    new_df['Metric'] = metric
    df = pd.concat([df, new_df], ignore_index=True)
    return df

def get_dict_string_void_list_from_keys_in_list(keys: list) -> dict:
    """Create a dictionary with string keys mapped to empty lists.
    
    Generates a dictionary where each element from the input list becomes a string
    key associated with an empty list value. Used for initializing result containers
    that will be populated during model execution.
    
    Args:
        keys (list): List of items to use as dictionary keys (typically plant IDs
            or technology identifiers).
    
    Returns:
        dict: Dictionary with string-converted keys from the input list, each mapped
            to an empty list.
    
    Example:
        >>> get_dict_string_void_list_from_keys_in_list([101, 202, 303])
        {'101': [], '202': [], '303': []}
    """  
    generic_dict = {}
    for plant in keys:
        generic_dict[str(plant)] = []
    return generic_dict