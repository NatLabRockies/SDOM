"""Preserve the historical I/O API while implementations live in ``sdom.io``.

New internal callers should import from the owning implementation module.
Supported public functions and input-helper aliases remain available.
Deprecated direct-model export and its private helpers have been removed.
"""

from .io import validation as _validation
from .io.aggregation import (
    _aggregate_to_single_area as _aggregate_to_single_area,
)
from .io.aggregation import (
    _capacity_weighted_average_prices as _capacity_weighted_average_prices,
)
from .io.aggregation import (
    _strip_area_tags_from_storage as _strip_area_tags_from_storage,
)
from .io.aggregation import (
    _sum_per_area_wide as _sum_per_area_wide,
)
from .io.areas import (
    _augment_with_per_area_views as _augment_with_per_area_views,
)
from .io.areas import (
    _combine_per_area_imp_exp as _combine_per_area_imp_exp,
)
from .io.areas import (
    _load_areas as _load_areas,
)
from .io.areas import (
    _parse_area_tagged_header as _parse_area_tagged_header,
)
from .io.areas import (
    _split_cf_by_plant_area as _split_cf_by_plant_area,
)
from .io.areas import (
    _split_row_by_area as _split_row_by_area,
)
from .io.areas import (
    _split_wide_by_area as _split_wide_by_area,
)
from .io.export import (
    export_results as export_results,
)
from .io.formulations import (
    get_formulation as get_formulation,
)
from .io.formulations import (
    get_network_formulation as get_network_formulation,
)
from .io.loader import (
    load_data as load_data,
)
from .io.loader import (
    load_thermal_min_dispatch as load_thermal_min_dispatch,
)
from .io.network import (
    _load_interconnections as _load_interconnections,
)
from .io.network import (
    _load_line_capacities as _load_line_capacities,
)
from .io.network import (
    _load_one_line_cap as _load_one_line_cap,
)
from .io.validation import (
    check_formulation as check_formulation,
)
from .io.validation import (
    validate_thermal_min_dispatch as validate_thermal_min_dispatch,
)

_validate_observed_areas = _validation.validate_observed_areas
