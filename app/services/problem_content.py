import html
import json
import math
import re
from uuid import uuid4
from sqlalchemy import inspect as sa_inspect

from app.extensions import db
from app.models.problems import (
    PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
    PROBLEM_ANSWER_TYPE_TEXT_INPUT,
    PROBLEM_BLOCK_TYPE_GRAPH,
    PROBLEM_BLOCK_TYPE_IMAGE,
    PROBLEM_BLOCK_TYPE_RICH_TEXT,
    ProblemAcceptedAnswer,
    ProblemBlock,
    ProblemChoiceOption,
)

# Structured problem-content helpers.
#
# Canonical authored content flows through structured rows:
# - body content via ProblemBlock
# - text-input answers via ProblemAcceptedAnswer
# - multiple-choice correctness via ProblemChoiceOption
#
# Legacy fields on Problem (prompt_text, answer_text, image_path) remain in use
# as compatibility mirrors and fallback-only reads for older content. New
# authoring and shared rendering should treat the structured rows as the
# primary source.


ANSWER_TYPE_CHOICES = [
    (PROBLEM_ANSWER_TYPE_TEXT_INPUT, 'Text input'),
    (PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE, 'Multiple choice'),
]

EDITOR_BLOCK_TYPE_CHOICES = [
    (PROBLEM_BLOCK_TYPE_RICH_TEXT, 'Rich text'),
    (PROBLEM_BLOCK_TYPE_IMAGE, 'Image'),
    (PROBLEM_BLOCK_TYPE_GRAPH, 'Graph'),
]

GRAPH_FUNCTION_FAMILIES = ('linear', 'quadratic', 'exponential', 'sine', 'cosine')
_GRAPH_NUMBER_RE = r'(?:\d+(?:\.\d+)?|\.\d+)'


def _default_graph_viewport() -> dict:
    return {
        'x_min': -10.0,
        'x_max': 10.0,
        'y_min': -10.0,
        'y_max': 10.0,
        'x_label': 'x',
        'y_label': 'y',
        'show_grid': True,
    }


def _graph_bool(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'on', 'yes'}


def _graph_float(value, field_label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field_label} must be a number.')


def _make_graph_element_id() -> str:
    return uuid4().hex[:10]


def _graph_optional_float(value, field_label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return _graph_float(value, field_label)


def _parse_signed_number(token: str, field_label: str) -> float:
    try:
        return float(token)
    except (TypeError, ValueError):
        raise ValueError(f'{field_label} must be a number.')


def _parse_optional_multiplier(token: str | None, *, default: float, field_label: str) -> float:
    if token is None or token == '' or token == '+':
        return default
    if token == '-':
        return -default
    return _parse_signed_number(token, field_label)


def _split_signed_terms(expr: str) -> list[str]:
    terms = re.findall(r'[+-]?[^+-]+', expr)
    if not terms or ''.join(terms) != expr:
        raise ValueError('Unsupported quadratic equation syntax.')
    return terms


def parse_graph_equation_text(equation_text: str) -> dict:
    raw = '' if equation_text is None else str(equation_text)
    compact = re.sub(r'\s+', '', raw).lower()
    if not compact:
        raise ValueError('Equation text is required.')
    if not compact.startswith('y='):
        raise ValueError('Equation must start with "y =".')

    expr = compact[2:]
    linear_match = re.fullmatch(rf'(?P<m>[+-]?(?:{_GRAPH_NUMBER_RE})?)x(?P<b>[+-]{_GRAPH_NUMBER_RE})?', expr)
    if linear_match:
        return {
            'element_type': 'function',
            'family': 'linear',
            'm': _parse_optional_multiplier(linear_match.group('m'), default=1.0, field_label='Linear slope'),
            'b': _graph_optional_float(linear_match.group('b'), 'Linear intercept') or 0.0,
        }

    exp_match = re.fullmatch(rf'(?:(?P<a>[+-]?{_GRAPH_NUMBER_RE})\*)?(?P<base>{_GRAPH_NUMBER_RE})\^x', expr)
    if exp_match:
        return {
            'element_type': 'function',
            'family': 'exponential',
            'a': _parse_optional_multiplier(exp_match.group('a'), default=1.0, field_label='Exponential coefficient'),
            'base': _parse_signed_number(exp_match.group('base'), 'Exponential base'),
        }

    trig_match = re.fullmatch(
        rf'(?P<a>[+-]?(?:{_GRAPH_NUMBER_RE})?)?(?:\*)?(?P<func>sin|cos)\((?P<b>[+-]?(?:{_GRAPH_NUMBER_RE})?)?x\)(?P<c>[+-]{_GRAPH_NUMBER_RE})?',
        expr,
    )
    if trig_match:
        family = 'sine' if trig_match.group('func') == 'sin' else 'cosine'
        return {
            'element_type': 'function',
            'family': family,
            'amplitude': _parse_optional_multiplier(trig_match.group('a'), default=1.0, field_label=f'{family.title()} amplitude'),
            'frequency': _parse_optional_multiplier(trig_match.group('b'), default=1.0, field_label=f'{family.title()} frequency'),
            'phase': 0.0,
            'vertical_shift': _graph_optional_float(trig_match.group('c'), f'{family.title()} vertical shift') or 0.0,
        }

    if 'x^2' in expr:
        a = b = c = None
        for term in _split_signed_terms(expr):
            if 'x^2' in term:
                if term.count('x^2') != 1 or term.replace('x^2', '') == '':
                    coeff_token = term.replace('x^2', '')
                else:
                    coeff_token = term.replace('x^2', '')
                if a is not None or term.endswith(('x^2x', 'x^2^')):
                    raise ValueError('Unsupported quadratic equation syntax.')
                a = _parse_optional_multiplier(coeff_token, default=1.0, field_label='Quadratic a')
            elif 'x' in term:
                if term.count('x') != 1 or '^' in term:
                    raise ValueError('Unsupported quadratic equation syntax.')
                if b is not None:
                    raise ValueError('Unsupported quadratic equation syntax.')
                b = _parse_optional_multiplier(term.replace('x', ''), default=1.0, field_label='Quadratic b')
            else:
                if c is not None:
                    raise ValueError('Unsupported quadratic equation syntax.')
                c = _parse_signed_number(term, 'Quadratic c')
        if a is not None:
            return {
                'element_type': 'function',
                'family': 'quadratic',
                'a': a,
                'b': b or 0.0,
                'c': c or 0.0,
            }

    raise ValueError('Unsupported graph equation syntax.')


def parse_graph_point_text(point_text: str) -> dict:
    raw = '' if point_text is None else str(point_text)
    compact = raw.strip()
    if not compact:
        raise ValueError('Point coordinates are required.')
    match = re.fullmatch(
        r'(?:\(\s*([+-]?' + _GRAPH_NUMBER_RE + r')\s*[,;]\s*([+-]?' + _GRAPH_NUMBER_RE + r')\s*\)|([+-]?' + _GRAPH_NUMBER_RE + r')\s*[,;]\s*([+-]?' + _GRAPH_NUMBER_RE + r'))',
        compact,
    )
    if not match:
        raise ValueError('Point coordinates must use x,y or x;y format.')
    x_token = match.group(1) or match.group(3)
    y_token = match.group(2) or match.group(4)
    return {
        'element_type': 'point',
        'x': _parse_signed_number(x_token, 'Point x'),
        'y': _parse_signed_number(y_token, 'Point y'),
    }


def convert_equation_to_graph_element(
    equation_text: str,
    *,
    label: str = '',
    color: str = '',
    x_min: float | None = None,
    x_max: float | None = None,
) -> dict:
    element = parse_graph_equation_text(equation_text)
    element['id'] = _make_graph_element_id()
    element['label'] = (label or '').strip()
    element['color'] = (color or '').strip()
    if x_min is not None or x_max is not None:
        if x_min is None or x_max is None:
            raise ValueError('Equation x-range requires both x_min and x_max.')
        x_min_value = _graph_float(x_min, 'Equation x minimum')
        x_max_value = _graph_float(x_max, 'Equation x maximum')
        if x_min_value >= x_max_value:
            raise ValueError('Equation x minimum must be less than x maximum.')
        element['x_min'] = x_min_value
        element['x_max'] = x_max_value
    return element


def convert_point_to_graph_element(point_text: str, *, label: str = '', color: str = '') -> dict:
    element = parse_graph_point_text(point_text)
    element['id'] = _make_graph_element_id()
    element['label'] = (label or '').strip()
    element['color'] = (color or '').strip()
    return element


def _format_graph_number(value: float) -> str:
    numeric = float(value)
    if abs(numeric) < 1e-12:
        numeric = 0.0
    if numeric.is_integer():
        return str(int(numeric))
    return f'{numeric:.12f}'.rstrip('0').rstrip('.')


def _format_linear_equation(m: float, b: float) -> str:
    if m == 1:
        base = 'x'
    elif m == -1:
        base = '-x'
    else:
        base = f'{_format_graph_number(m)}x'
    if b == 0:
        return f'y = {base}'
    sign = '+' if b > 0 else '-'
    return f'y = {base} {sign} {_format_graph_number(abs(b))}'


def _format_quadratic_term(coefficient: float, variable: str) -> str:
    if coefficient == 1:
        return variable
    if coefficient == -1:
        return f'-{variable}'
    return f'{_format_graph_number(coefficient)}{variable}'


def _format_quadratic_equation(a: float, b: float, c: float) -> str:
    terms = [_format_quadratic_term(a, 'x^2')]
    if b != 0:
        terms.append(_format_quadratic_term(b, 'x'))
    if c != 0:
        terms.append(_format_graph_number(c))
    rendered = terms[0]
    for term in terms[1:]:
        if term.startswith('-'):
            rendered += f' - {term[1:]}'
        else:
            rendered += f' + {term}'
    return f'y = {rendered}'


def _format_exponential_equation(a: float, base: float) -> str:
    base_text = _format_graph_number(base)
    if a == 1:
        return f'y = {base_text}^x'
    return f'y = {_format_graph_number(a)}*{base_text}^x'


def _format_trig_equation(family: str, amplitude: float, frequency: float, phase: float, vertical_shift: float) -> str | None:
    if abs(float(phase)) > 1e-12:
        return None
    func_name = 'sin' if family == 'sine' else 'cos'
    frequency_text = 'x' if frequency == 1 else f'{_format_graph_number(frequency)}x'
    if amplitude == 1:
        expr = f'{func_name}({frequency_text})'
    elif amplitude == -1:
        expr = f'-{func_name}({frequency_text})'
    else:
        expr = f'{_format_graph_number(amplitude)}*{func_name}({frequency_text})'
    if vertical_shift == 0:
        return f'y = {expr}'
    sign = '+' if vertical_shift > 0 else '-'
    return f'y = {expr} {sign} {_format_graph_number(abs(vertical_shift))}'


def format_graph_equation_from_element(element: dict) -> str | None:
    if element.get('element_type') != 'function':
        return None
    family = element.get('family')
    if family == 'linear':
        return _format_linear_equation(element['m'], element['b'])
    if family == 'quadratic':
        return _format_quadratic_equation(element['a'], element['b'], element['c'])
    if family == 'exponential':
        return _format_exponential_equation(element['a'], element['base'])
    if family in {'sine', 'cosine'}:
        return _format_trig_equation(
            family,
            element['amplitude'],
            element['frequency'],
            element['phase'],
            element['vertical_shift'],
        )
    return None


def format_graph_point_text(element: dict) -> str | None:
    if element.get('element_type') != 'point':
        return None
    return f'({_format_graph_number(element["x"])}, {_format_graph_number(element["y"])})'


def _load_graph_config(block) -> dict:
    raw = (block.graph_config_json or '').strip()
    if not raw:
        return {
            **_default_graph_viewport(),
            'elements': [],
        }
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError('Graph configuration is invalid JSON.')
    if not isinstance(loaded, dict):
        raise ValueError('Graph configuration must be an object.')
    return loaded


def _normalize_graph_element(raw: dict, *, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError('Graph element configuration must be an object.')

    element_type = (raw.get('element_type') or '').strip().lower()
    if element_type not in {'function', 'point'}:
        raise ValueError('Graph elements must be function traces or point markers.')

    element_id = (raw.get('id') or '').strip() or _make_graph_element_id()
    label = (raw.get('label') or '').strip()
    color = (raw.get('color') or '').strip()

    if element_type == 'point':
        return {
            'id': element_id,
            'element_type': 'point',
            'label': label,
            'color': color,
            'x': _graph_float(raw.get('x'), f'Graph point #{index} x'),
            'y': _graph_float(raw.get('y'), f'Graph point #{index} y'),
        }

    family = (raw.get('family') or '').strip().lower()
    if family not in GRAPH_FUNCTION_FAMILIES:
        raise ValueError('Unsupported graph function family.')

    normalized = {
        'id': element_id,
        'element_type': 'function',
        'family': family,
        'label': label,
        'color': color,
    }
    x_min = _graph_optional_float(raw.get('x_min'), f'Graph function #{index} x minimum')
    x_max = _graph_optional_float(raw.get('x_max'), f'Graph function #{index} x maximum')
    if x_min is not None or x_max is not None:
        if x_min is None or x_max is None:
            raise ValueError('Graph function x-range requires both x minimum and x maximum.')
        if x_min >= x_max:
            raise ValueError('Graph function x minimum must be less than x maximum.')
        normalized['x_min'] = x_min
        normalized['x_max'] = x_max
    if family == 'linear':
        normalized['m'] = _graph_float(raw.get('m'), f'Linear trace #{index} slope')
        normalized['b'] = _graph_float(raw.get('b'), f'Linear trace #{index} intercept')
    elif family == 'quadratic':
        normalized['a'] = _graph_float(raw.get('a'), f'Quadratic trace #{index} a')
        normalized['b'] = _graph_float(raw.get('b'), f'Quadratic trace #{index} b')
        normalized['c'] = _graph_float(raw.get('c'), f'Quadratic trace #{index} c')
    elif family == 'exponential':
        normalized['a'] = _graph_float(raw.get('a'), f'Exponential trace #{index} coefficient')
        normalized['base'] = _graph_float(raw.get('base'), f'Exponential trace #{index} base')
        if normalized['base'] <= 0:
            raise ValueError('Exponential trace base must be greater than 0.')
    elif family == 'sine':
        normalized['amplitude'] = _graph_float(raw.get('amplitude'), f'Sine trace #{index} amplitude')
        normalized['frequency'] = _graph_float(raw.get('frequency'), f'Sine trace #{index} frequency')
        normalized['phase'] = _graph_float(raw.get('phase'), f'Sine trace #{index} phase')
        normalized['vertical_shift'] = _graph_float(raw.get('vertical_shift'), f'Sine trace #{index} vertical shift')
    elif family == 'cosine':
        normalized['amplitude'] = _graph_float(raw.get('amplitude'), f'Cosine trace #{index} amplitude')
        normalized['frequency'] = _graph_float(raw.get('frequency'), f'Cosine trace #{index} frequency')
        normalized['phase'] = _graph_float(raw.get('phase'), f'Cosine trace #{index} phase')
        normalized['vertical_shift'] = _graph_float(raw.get('vertical_shift'), f'Cosine trace #{index} vertical shift')
    return normalized


def normalize_graph_block_config(raw_config: dict | None) -> dict:
    if raw_config is None:
        raw_config = {}
    if not isinstance(raw_config, dict):
        raise ValueError('Graph configuration must be an object.')

    defaults = _default_graph_viewport()
    normalized = {
        'x_min': _graph_float(raw_config.get('x_min', defaults['x_min']), 'Graph x minimum'),
        'x_max': _graph_float(raw_config.get('x_max', defaults['x_max']), 'Graph x maximum'),
        'y_min': _graph_float(raw_config.get('y_min', defaults['y_min']), 'Graph y minimum'),
        'y_max': _graph_float(raw_config.get('y_max', defaults['y_max']), 'Graph y maximum'),
        'x_label': (raw_config.get('x_label') or defaults['x_label']).strip(),
        'y_label': (raw_config.get('y_label') or defaults['y_label']).strip(),
        'show_grid': _graph_bool(raw_config.get('show_grid'), defaults['show_grid']),
    }

    if normalized['x_min'] >= normalized['x_max']:
        raise ValueError('Graph x minimum must be less than x maximum.')
    if normalized['y_min'] >= normalized['y_max']:
        raise ValueError('Graph y minimum must be less than y maximum.')

    raw_elements = raw_config.get('elements') or []
    if not isinstance(raw_elements, list):
        raise ValueError('Graph elements must be a list.')

    normalized['elements'] = [
        _normalize_graph_element(element, index=index)
        for index, element in enumerate(raw_elements, start=1)
    ]
    return normalized


def _dump_graph_config(config: dict) -> str:
    return json.dumps(config, sort_keys=True)


def _build_graph_plot_payload(graph_config: dict) -> dict:
    x_min = graph_config['x_min']
    x_max = graph_config['x_max']
    y_min = graph_config['y_min']
    y_max = graph_config['y_max']
    traces = []

    for element in graph_config['elements']:
        if element['element_type'] == 'point':
            hover = element['label'] + '<br>' if element['label'] else ''
            hover += '(%{x}, %{y})'
            traces.append({
                'type': 'scatter',
                'mode': 'markers+text' if element['label'] else 'markers',
                'x': [element['x']],
                'y': [element['y']],
                'text': [element['label']] if element['label'] else None,
                'textposition': 'top center',
                'name': element['label'] or 'Point',
                'marker': {
                    'size': 10,
                    'color': element['color'] or '#d62728',
                },
                'hovertemplate': hover + '<extra></extra>',
            })
            continue

        family = element['family']
        trace_x_min = element.get('x_min', x_min)
        trace_x_max = element.get('x_max', x_max)
        x_values = [trace_x_min + (trace_x_max - trace_x_min) * (idx / 119.0) for idx in range(120)]
        y_values = []
        for x in x_values:
            if family == 'linear':
                y = element['m'] * x + element['b']
            elif family == 'quadratic':
                y = element['a'] * x * x + element['b'] * x + element['c']
            elif family == 'exponential':
                y = element['a'] * (element['base'] ** x)
            elif family == 'sine':
                y = element['amplitude'] * math.sin(element['frequency'] * (x - element['phase'])) + element['vertical_shift']
            else:
                y = element['amplitude'] * math.cos(element['frequency'] * (x - element['phase'])) + element['vertical_shift']
            y_values.append(y)

        label = element['label'] or family.replace('_', ' ').title()
        traces.append({
            'type': 'scatter',
            'mode': 'lines',
            'x': x_values,
            'y': y_values,
            'name': label,
            'line': {
                'color': element['color'] or '#1f77b4',
                'width': 3,
            },
            'hovertemplate': '%{x}, %{y}<extra>' + html.escape(label) + '</extra>',
        })

    return {
        'data': traces,
        'layout': {
            'margin': {'l': 46, 'r': 18, 't': 18, 'b': 42},
            'paper_bgcolor': '#ffffff',
            'plot_bgcolor': '#ffffff',
            'showlegend': bool(traces),
            'dragmode': 'pan',
            'xaxis': {
                'title': graph_config['x_label'],
                'range': [x_min, x_max],
                'showgrid': graph_config['show_grid'],
                'zeroline': True,
            },
            'yaxis': {
                'title': graph_config['y_label'],
                'range': [y_min, y_max],
                'showgrid': graph_config['show_grid'],
                'zeroline': True,
                'scaleanchor': False,
            },
        },
        'config': {
            'responsive': True,
            'scrollZoom': True,
            'displaylogo': False,
            'modeBarButtonsToRemove': ['select2d', 'lasso2d', 'autoScale2d'],
        },
    }


def build_graph_block_editor_view(block) -> dict:
    graph_config = normalize_graph_block_config(_load_graph_config(block))
    equation_rows = []
    point_rows = []
    unsupported_elements = []

    for element in graph_config['elements']:
        if element['element_type'] == 'point':
            point_rows.append({
                'id': element['id'],
                'label': element['label'],
                'color': element['color'],
                'coordinates_text': format_graph_point_text(element) or '',
            })
            continue

        equation_text = format_graph_equation_from_element(element)
        if equation_text:
            equation_rows.append({
                'id': element['id'],
                'label': element['label'],
                'color': element['color'],
                'equation_text': equation_text,
                'x_min': '' if element.get('x_min') is None else _format_graph_number(element['x_min']),
                'x_max': '' if element.get('x_max') is None else _format_graph_number(element['x_max']),
                'family': element['family'],
            })
        else:
            unsupported_elements.append({
                'id': element['id'],
                'label': element['label'],
                'color': element['color'],
                'family': element.get('family', 'function'),
                'summary': 'This saved graph element uses a legacy parameter combination that cannot yet round-trip through equation rows. It will be preserved as-is when you save this block.',
            })

    return {
        'viewport': {
            'x_min': graph_config['x_min'],
            'x_max': graph_config['x_max'],
            'y_min': graph_config['y_min'],
            'y_max': graph_config['y_max'],
            'x_label': graph_config['x_label'],
            'y_label': graph_config['y_label'],
            'show_grid': graph_config['show_grid'],
        },
        'equations': equation_rows,
        'points': point_rows,
        'unsupported_elements': unsupported_elements,
    }


def add_graph_block_element(block, element_type: str) -> None:
    graph_config = normalize_graph_block_config(_load_graph_config(block))
    normalized_type = (element_type or '').strip().lower()
    if normalized_type == 'point':
        graph_config['elements'].append({
            'id': _make_graph_element_id(),
            'element_type': 'point',
            'label': '',
            'color': '',
            'x': 0.0,
            'y': 0.0,
        })
    elif normalized_type == 'equation':
        graph_config['elements'].append({
            'id': _make_graph_element_id(),
            'element_type': 'function',
            'family': 'linear',
            'label': '',
            'color': '',
            'm': 1.0,
            'b': 0.0,
        })
    elif normalized_type in GRAPH_FUNCTION_FAMILIES:
        element = {
            'id': _make_graph_element_id(),
            'element_type': 'function',
            'family': normalized_type,
            'label': '',
            'color': '',
        }
        if normalized_type == 'linear':
            element.update({'m': 1.0, 'b': 0.0})
        elif normalized_type == 'quadratic':
            element.update({'a': 1.0, 'b': 0.0, 'c': 0.0})
        elif normalized_type == 'exponential':
            element.update({'a': 1.0, 'base': 2.0})
        elif normalized_type == 'sine':
            element.update({'amplitude': 1.0, 'frequency': 1.0, 'phase': 0.0, 'vertical_shift': 0.0})
        else:
            element.update({'amplitude': 1.0, 'frequency': 1.0, 'phase': 0.0, 'vertical_shift': 0.0})
        graph_config['elements'].append(element)
    else:
        raise ValueError('Unsupported graph element type.')

    block.graph_config_json = _dump_graph_config(graph_config)


def delete_graph_block_element(block, element_id: str) -> None:
    graph_config = normalize_graph_block_config(_load_graph_config(block))
    remaining = [row for row in graph_config['elements'] if row['id'] != element_id]
    if len(remaining) == len(graph_config['elements']):
        raise ValueError('Graph element not found.')
    graph_config['elements'] = remaining
    block.graph_config_json = _dump_graph_config(graph_config)


def normalize_text_input_answer(value: str | None) -> str:
    if value is None:
        return ''
    collapsed = re.sub(r'\s+', ' ', str(value)).strip()
    return collapsed.lower()


def get_legacy_problem_prompt_text(problem) -> str:
    """Return the legacy root prompt_text fallback for pre-structured records."""
    return (getattr(problem, 'prompt_text', '') or '').strip()


def get_legacy_problem_answer_text(problem) -> str:
    """Return the legacy root answer_text fallback for compatibility-only reads."""
    return (getattr(problem, 'answer_text', '') or '').strip()


def get_legacy_problem_image_path(problem) -> str:
    """Return the legacy root image_path fallback for pre-block body content."""
    return (getattr(problem, 'image_path', '') or '').strip()


def get_problem_answer_variants(problem) -> list[str]:
    """Return accepted text answers from the canonical structured source first.

    Structured ProblemAcceptedAnswer rows are authoritative for text-input
    problems. problem.answer_text remains as a compatibility fallback for older
    records that have not been initialized into structured answers yet.
    """
    answers = [row.answer_text for row in problem.accepted_answers if (row.answer_text or '').strip()]
    if answers:
        return answers
    legacy_answer = get_legacy_problem_answer_text(problem)
    if legacy_answer:
        return [legacy_answer]
    return []


def check_problem_text_input_answer(problem, submitted_text: str | None) -> bool:
    """Validate text input against structured accepted answers with legacy fallback."""
    submitted = normalize_text_input_answer(submitted_text)
    if not submitted:
        return False

    accepted = [
        normalize_text_input_answer(answer_text)
        for answer_text in get_problem_answer_variants(problem)
        if normalize_text_input_answer(answer_text)
    ]
    return submitted in accepted


def check_problem_multiple_choice_answer(problem, submitted_option_id: int | None) -> bool:
    if submitted_option_id is None:
        return False
    correct_options = [option.id for option in problem.choice_options if option.is_correct]
    return len(correct_options) == 1 and submitted_option_id == correct_options[0]


def render_inline_text_html(source: str | None) -> str:
    raw = '' if source is None else str(source)
    escaped = html.escape(raw)
    escaped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)
    escaped = escaped.replace('\n', '<br>')
    return escaped


def render_rich_text_html(source: str | None) -> str:
    raw = '' if source is None else str(source)
    if not raw.strip():
        return '<p class="problem-body-empty">Empty text block.</p>'

    paragraphs = re.split(r'\n\s*\n', raw.strip())
    rendered_parts = []
    for paragraph in paragraphs:
        rendered_parts.append(f'<p>{render_inline_text_html(paragraph)}</p>')
    return ''.join(rendered_parts)


def normalize_problem_block_positions(problem) -> None:
    live_blocks = [block for block in problem.blocks if not sa_inspect(block).deleted]
    ordered_blocks = sorted(live_blocks, key=lambda block: (block.position, block.id or 0))
    for index, block in enumerate(ordered_blocks, start=1):
        block.position = index


def has_saved_problem_blocks(problem) -> bool:
    return bool(problem.blocks)


def has_saved_problem_accepted_answers(problem) -> bool:
    return bool(problem.accepted_answers)


def has_saved_problem_choice_options(problem) -> bool:
    return bool(problem.choice_options)


def uses_structured_problem_answers(problem) -> bool:
    """Report whether the problem already participates in the structured answer model."""
    return (
        getattr(problem, 'answer_type', PROBLEM_ANSWER_TYPE_TEXT_INPUT) == PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE
        or has_saved_problem_accepted_answers(problem)
        or has_saved_problem_choice_options(problem)
    )


def ensure_problem_default_block(problem) -> ProblemBlock:
    """Bootstrap the first structured body block from legacy prompt_text if needed."""
    if problem.blocks:
        normalize_problem_block_positions(problem)
        return problem.blocks[0]

    block = ProblemBlock(
        problem_id=problem.id,
        position=1,
        block_type=PROBLEM_BLOCK_TYPE_RICH_TEXT,
        text_content=get_legacy_problem_prompt_text(problem),
    )
    db.session.add(block)
    db.session.flush()
    return block


def ensure_problem_default_accepted_answer(problem) -> ProblemAcceptedAnswer | None:
    """Bootstrap the first structured accepted-answer row from legacy answer_text."""
    if problem.accepted_answers:
        return problem.accepted_answers[0]
    legacy_answer = get_legacy_problem_answer_text(problem)
    if not legacy_answer:
        return None
    answer = ProblemAcceptedAnswer(
        problem_id=problem.id,
        position=1,
        answer_text=legacy_answer,
    )
    db.session.add(answer)
    db.session.flush()
    return answer


def ensure_problem_default_choice_options(problem, *, count: int = 4) -> list[ProblemChoiceOption]:
    if problem.choice_options:
        normalize_problem_choice_option_positions(problem)
        return sorted(problem.choice_options, key=lambda option: (option.position, option.id or 0))

    created = []
    for position in range(1, count + 1):
        option = ProblemChoiceOption(
            problem_id=problem.id,
            position=position,
            option_text='',
            is_correct=(position == 1),
        )
        db.session.add(option)
        created.append(option)
    db.session.flush()
    return created


def sync_problem_legacy_compat_fields(problem) -> None:
    """Mirror canonical structured content back into legacy Problem fields.

    This keeps prompt_text / image_path / answer_text populated for compatibility
    with older code paths and fixtures. These mirrored fields are not the primary
    authored source for new content.
    """
    ordered_blocks = sorted(problem.blocks, key=lambda block: (block.position, block.id or 0))
    rich_text_segments = []
    first_image_path = None

    for block in ordered_blocks:
        if block.block_type == PROBLEM_BLOCK_TYPE_RICH_TEXT:
            text_content = (block.text_content or '').strip()
            if text_content:
                rich_text_segments.append(text_content)
        elif block.block_type == PROBLEM_BLOCK_TYPE_IMAGE and first_image_path is None:
            image_path = (block.image_path or '').strip()
            if image_path:
                first_image_path = image_path

    problem.prompt_text = '\n\n'.join(rich_text_segments)
    problem.image_path = first_image_path

    if getattr(problem, 'answer_type', PROBLEM_ANSWER_TYPE_TEXT_INPUT) == PROBLEM_ANSWER_TYPE_TEXT_INPUT:
        ordered_answers = sorted(problem.accepted_answers, key=lambda row: (row.position, row.id or 0))
        problem.answer_text = next(
            ((row.answer_text or '').strip() for row in ordered_answers if (row.answer_text or '').strip()),
            '',
        )
        return

    ordered_options = sorted(problem.choice_options, key=lambda row: (row.position, row.id or 0))
    correct_option = next(
        (
            (row.option_text or '').strip()
            for row in ordered_options
            if row.is_correct and (row.option_text or '').strip()
        ),
        '',
    )
    problem.answer_text = correct_option


def add_problem_block(problem, block_type: str, *, after_block_id: int | None = None) -> ProblemBlock:
    if block_type not in {PROBLEM_BLOCK_TYPE_RICH_TEXT, PROBLEM_BLOCK_TYPE_IMAGE, PROBLEM_BLOCK_TYPE_GRAPH}:
        raise ValueError('Unsupported block type.')

    normalize_problem_block_positions(problem)
    insert_position = len(problem.blocks) + 1
    if after_block_id is not None:
        anchor = next((row for row in problem.blocks if row.id == after_block_id), None)
        if anchor is None:
            raise ValueError('Problem block not found.')
        insert_position = anchor.position + 1
        for block in sorted(problem.blocks, key=lambda row: (row.position, row.id or 0)):
            if block.position >= insert_position:
                block.position += 1

    block = ProblemBlock(
        problem_id=problem.id,
        position=insert_position,
        block_type=block_type,
        text_content='' if block_type == PROBLEM_BLOCK_TYPE_RICH_TEXT else None,
        image_path='' if block_type == PROBLEM_BLOCK_TYPE_IMAGE else None,
        image_width_pct=100 if block_type == PROBLEM_BLOCK_TYPE_IMAGE else None,
        graph_config_json=_dump_graph_config({
            **_default_graph_viewport(),
            'elements': [],
        }) if block_type == PROBLEM_BLOCK_TYPE_GRAPH else None,
    )
    db.session.add(block)
    db.session.flush()
    return block


def normalize_problem_choice_option_positions(problem) -> None:
    live_options = [option for option in problem.choice_options if not sa_inspect(option).deleted]
    ordered_options = sorted(live_options, key=lambda option: (option.position, option.id or 0))
    for index, option in enumerate(ordered_options, start=1):
        option.position = index


def add_problem_choice_option(problem) -> ProblemChoiceOption:
    normalize_problem_choice_option_positions(problem)
    next_position = len(problem.choice_options) + 1
    option = ProblemChoiceOption(
        problem_id=problem.id,
        position=next_position,
        option_text='',
        is_correct=False,
    )
    db.session.add(option)
    db.session.flush()
    return option


def move_problem_choice_option(problem, option_id: int, direction: str) -> None:
    normalize_problem_choice_option_positions(problem)
    ordered = sorted(problem.choice_options, key=lambda option: (option.position, option.id or 0))
    current_index = next((idx for idx, option in enumerate(ordered) if option.id == option_id), None)
    if current_index is None:
        raise ValueError('Problem choice option not found.')

    if direction == 'up' and current_index > 0:
        ordered[current_index - 1], ordered[current_index] = ordered[current_index], ordered[current_index - 1]
    elif direction == 'down' and current_index < len(ordered) - 1:
        ordered[current_index + 1], ordered[current_index] = ordered[current_index], ordered[current_index + 1]
    else:
        return

    for index, option in enumerate(ordered, start=1):
        option.position = index


def delete_problem_choice_option(problem, option_id: int) -> None:
    option = next((row for row in problem.choice_options if row.id == option_id), None)
    if option is None:
        raise ValueError('Problem choice option not found.')
    db.session.delete(option)
    db.session.flush()
    normalize_problem_choice_option_positions(problem)


def move_problem_block(problem, block_id: int, direction: str) -> None:
    normalize_problem_block_positions(problem)
    ordered = sorted(problem.blocks, key=lambda block: (block.position, block.id or 0))
    current_index = next((idx for idx, block in enumerate(ordered) if block.id == block_id), None)
    if current_index is None:
        raise ValueError('Problem block not found.')

    if direction == 'up' and current_index > 0:
        ordered[current_index - 1], ordered[current_index] = ordered[current_index], ordered[current_index - 1]
    elif direction == 'down' and current_index < len(ordered) - 1:
        ordered[current_index + 1], ordered[current_index] = ordered[current_index], ordered[current_index + 1]
    else:
        return

    for index, block in enumerate(ordered, start=1):
        block.position = index


def delete_problem_block(problem, block_id: int) -> None:
    block = next((row for row in problem.blocks if row.id == block_id), None)
    if block is None:
        raise ValueError('Problem block not found.')
    db.session.delete(block)
    db.session.flush()
    normalize_problem_block_positions(problem)


def replace_problem_accepted_answers(problem, answer_lines: list[str]) -> None:
    cleaned = []
    for raw in answer_lines:
        text = (raw or '').strip()
        if text:
            cleaned.append(text)

    for row in list(problem.accepted_answers):
        db.session.delete(row)
    db.session.flush()

    for index, answer_text in enumerate(cleaned, start=1):
        db.session.add(
            ProblemAcceptedAnswer(
                problem_id=problem.id,
                position=index,
                answer_text=answer_text,
            )
        )
    db.session.flush()


def update_problem_choice_options(problem, choice_payloads: list[dict], correct_option_id: int | None) -> None:
    ordered_rows = sorted(problem.choice_options, key=lambda option: (option.position, option.id or 0))
    if not ordered_rows:
        raise ValueError('Multiple-choice problems require at least two options.')

    if len(ordered_rows) < 2:
        raise ValueError('Multiple-choice problems require at least two options.')

    if correct_option_id is None:
        raise ValueError('Select exactly one correct multiple-choice option.')

    valid_ids = {row.id for row in ordered_rows}
    if correct_option_id not in valid_ids:
        raise ValueError('Select exactly one correct multiple-choice option.')

    for payload in choice_payloads:
        option_id = payload['option_id']
        option = next((row for row in ordered_rows if row.id == option_id), None)
        if option is None:
            raise ValueError('Problem choice option not found.')
        option_text = (payload.get('option_text') or '').strip()
        if not option_text:
            raise ValueError('Multiple-choice options require text.')
        option.option_text = option_text
        option.is_correct = option.id == correct_option_id


def update_problem_block_content(problem, block_id: int, payload: dict) -> None:
    block = next((row for row in problem.blocks if row.id == block_id), None)
    if block is None:
        raise ValueError('Problem block not found.')

    if block.block_type == PROBLEM_BLOCK_TYPE_RICH_TEXT:
        block.text_content = (payload.get('text_content') or '').strip()
    elif block.block_type == PROBLEM_BLOCK_TYPE_IMAGE:
        image_path = (payload.get('image_path') or '').strip()
        if not image_path:
            raise ValueError('Image blocks require an image path.')
        try:
            width_pct = int(payload.get('image_width_pct') or 100)
        except (TypeError, ValueError):
            raise ValueError('Image width must be a whole-number percentage.')
        if width_pct < 1 or width_pct > 100:
            raise ValueError('Image width must be between 1 and 100 percent.')
        block.image_path = image_path
        block.image_width_pct = width_pct
    elif block.block_type == PROBLEM_BLOCK_TYPE_GRAPH:
        base_config = normalize_graph_block_config(_load_graph_config(block))
        graph_equations = payload.get('graph_equations')
        graph_points = payload.get('graph_points')
        if graph_equations is not None or graph_points is not None:
            elements = []
            equation_ids = {row['id'] for row in graph_equations or []}
            point_ids = {row['id'] for row in graph_points or []}
            preserved_elements = [
                element
                for element in base_config['elements']
                if element['id'] not in equation_ids and element['id'] not in point_ids
            ]

            for row in graph_equations or []:
                equation_text = row.get('equation_text')
                label = row.get('label') or ''
                color = row.get('color') or ''
                range_min = _graph_optional_float(row.get('x_min'), 'Equation x minimum')
                range_max = _graph_optional_float(row.get('x_max'), 'Equation x maximum')
                converted = convert_equation_to_graph_element(
                    equation_text,
                    label=label,
                    color=color,
                    x_min=range_min,
                    x_max=range_max,
                )
                converted['id'] = row['id']
                elements.append(converted)

            for row in graph_points or []:
                converted = convert_point_to_graph_element(
                    row.get('coordinates_text'),
                    label=row.get('label') or '',
                    color=row.get('color') or '',
                )
                converted['id'] = row['id']
                elements.append(converted)

            elements.extend(preserved_elements)
        else:
            elements = payload.get('graph_elements') or []
        updated_config = {
            'x_min': _graph_float(payload.get('graph_x_min', base_config['x_min']), 'Graph x minimum'),
            'x_max': _graph_float(payload.get('graph_x_max', base_config['x_max']), 'Graph x maximum'),
            'y_min': _graph_float(payload.get('graph_y_min', base_config['y_min']), 'Graph y minimum'),
            'y_max': _graph_float(payload.get('graph_y_max', base_config['y_max']), 'Graph y maximum'),
            'x_label': (payload.get('graph_x_label') or '').strip(),
            'y_label': (payload.get('graph_y_label') or '').strip(),
            'show_grid': _graph_bool(payload.get('graph_show_grid')),
            'elements': elements,
        }
        block.graph_config_json = _dump_graph_config(normalize_graph_block_config(updated_config))
    else:
        raise ValueError('Unsupported block type.')


def build_problem_choice_view(problem) -> dict:
    answer_type = getattr(problem, 'answer_type', PROBLEM_ANSWER_TYPE_TEXT_INPUT) or PROBLEM_ANSWER_TYPE_TEXT_INPUT
    ordered_options = sorted(problem.choice_options, key=lambda option: (option.position, option.id or 0))
    return {
        'answer_type': answer_type,
        'options': [
            {
                'id': option.id,
                'position': option.position,
                'option_text': option.option_text,
                'rendered_html': render_inline_text_html(option.option_text),
            }
            for option in ordered_options
        ],
    }


def build_problem_body_view(problem) -> dict:
    """Build the rendered problem body with structured blocks as the canonical source.

    When saved ProblemBlock rows exist, they fully define the body. Legacy
    problem.prompt_text and problem.image_path are only used as a fallback view
    for older records that have not been initialized into structured blocks yet.
    """
    blocks = sorted(problem.blocks, key=lambda row: (row.position, row.id or 0))
    body_blocks = []

    if blocks:
        for block in blocks:
            if block.block_type == PROBLEM_BLOCK_TYPE_RICH_TEXT:
                body_blocks.append({
                    'id': block.id,
                    'type': PROBLEM_BLOCK_TYPE_RICH_TEXT,
                    'position': block.position,
                    'text_content': block.text_content or '',
                    'rendered_html': render_rich_text_html(block.text_content or ''),
                })
            elif block.block_type == PROBLEM_BLOCK_TYPE_IMAGE:
                body_blocks.append({
                    'id': block.id,
                    'type': PROBLEM_BLOCK_TYPE_IMAGE,
                    'position': block.position,
                    'image_path': block.image_path or '',
                    'image_width_pct': block.image_width_pct or 100,
                })
            elif block.block_type == PROBLEM_BLOCK_TYPE_GRAPH:
                graph_config = normalize_graph_block_config(_load_graph_config(block))
                body_blocks.append({
                    'id': block.id,
                    'type': PROBLEM_BLOCK_TYPE_GRAPH,
                    'position': block.position,
                    'graph_config': graph_config,
                    'graph_payload': _build_graph_plot_payload(graph_config),
                })
        uses_legacy_fallback = False
    else:
        legacy_prompt = get_legacy_problem_prompt_text(problem)
        legacy_image_path = get_legacy_problem_image_path(problem)
        if legacy_prompt:
            body_blocks.append({
                'id': None,
                'type': PROBLEM_BLOCK_TYPE_RICH_TEXT,
                'position': 1,
                'text_content': legacy_prompt,
                'rendered_html': render_rich_text_html(legacy_prompt),
            })
        if legacy_image_path:
            body_blocks.append({
                'id': None,
                'type': PROBLEM_BLOCK_TYPE_IMAGE,
                'position': len(body_blocks) + 1,
                'image_path': legacy_image_path,
                'image_width_pct': 100,
            })
        uses_legacy_fallback = True

    return {
        'blocks': body_blocks,
        'uses_legacy_fallback': uses_legacy_fallback,
        'has_blocks': bool(body_blocks),
    }
