"""
Graph equation authoring Stage 1 focused tests.

Verifies:
  - narrow equation parsing for supported families
  - point coordinate parsing
  - conversion into normalized graph elements
  - cosine + per-equation x-range compatibility
  - rejected unsupported syntax
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.problem_content import (
    _build_graph_plot_payload,
    convert_equation_to_graph_element,
    convert_point_to_graph_element,
    normalize_graph_block_config,
    parse_graph_equation_text,
    parse_graph_point_text,
)


passed = 0
failed = 0


def check(label, condition, detail=''):
    global passed, failed
    if condition:
        print(f'  PASS  {label}')
        passed += 1
    else:
        msg = f'  FAIL  {label}'
        if detail:
            msg += f'  ({detail})'
        print(msg)
        failed += 1


def _raises_value_error(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError:
        return True
    return False


def run_tests():
    linear = parse_graph_equation_text('y = -0.5x - 3')
    check(
        'GES1-01: accepted linear equations parse',
        linear['family'] == 'linear' and linear['m'] == -0.5 and linear['b'] == -3.0,
    )

    quadratic = parse_graph_equation_text('y = 2x^2 - 3x + 1')
    check(
        'GES1-02: accepted quadratic equations parse',
        quadratic['family'] == 'quadratic' and quadratic['a'] == 2.0 and quadratic['b'] == -3.0 and quadratic['c'] == 1.0,
    )

    exponential = parse_graph_equation_text('y = 1.5*2^x')
    check(
        'GES1-03: accepted exponential equations parse',
        exponential['family'] == 'exponential' and exponential['a'] == 1.5 and exponential['base'] == 2.0,
    )

    sine = parse_graph_equation_text('y = -sin(x)')
    check(
        'GES1-04: accepted sine equations parse',
        sine['family'] == 'sine' and sine['amplitude'] == -1.0 and sine['frequency'] == 1.0 and sine['vertical_shift'] == 0.0,
    )

    cosine = parse_graph_equation_text('y = 2*cos(3x) + 4')
    check(
        'GES1-05: accepted cosine equations parse',
        cosine['family'] == 'cosine' and cosine['amplitude'] == 2.0 and cosine['frequency'] == 3.0 and cosine['vertical_shift'] == 4.0,
    )

    check(
        'GES1-06: unsupported equation syntax is rejected',
        _raises_value_error(parse_graph_equation_text, 'y = e^x')
        and _raises_value_error(parse_graph_equation_text, 'y = 2^(x+1)')
        and _raises_value_error(parse_graph_equation_text, 'x = 2y + 1')
        and _raises_value_error(parse_graph_equation_text, 'y = sin(x + 1)'),
    )

    point_a = parse_graph_point_text('2,3')
    point_b = parse_graph_point_text('2;3')
    point_c = parse_graph_point_text('(2, 3)')
    point_d = parse_graph_point_text('(2; 3)')
    check(
        'GES1-07: accepted point coordinate formats parse',
        point_a['x'] == 2.0 and point_a['y'] == 3.0
        and point_b['x'] == 2.0 and point_b['y'] == 3.0
        and point_c['x'] == 2.0 and point_c['y'] == 3.0
        and point_d['x'] == 2.0 and point_d['y'] == 3.0,
    )

    check(
        'GES1-08: malformed point coordinate syntax is rejected',
        _raises_value_error(parse_graph_point_text, '(2,3')
        and _raises_value_error(parse_graph_point_text, '2,')
        and _raises_value_error(parse_graph_point_text, '2 3'),
    )

    ranged = convert_equation_to_graph_element('y = x^2', label='Parabola', x_min=-2, x_max=3)
    point = convert_point_to_graph_element('(1; 4)', label='P')
    check(
        'GES1-09: conversion creates normalized elements with optional x-range',
        ranged['family'] == 'quadratic'
        and ranged['label'] == 'Parabola'
        and ranged['x_min'] == -2.0
        and ranged['x_max'] == 3.0
        and point['element_type'] == 'point'
        and point['label'] == 'P',
    )

    normalized = normalize_graph_block_config({
        'x_min': -10,
        'x_max': 10,
        'y_min': -6,
        'y_max': 6,
        'elements': [
            convert_equation_to_graph_element('y = cos(x)', x_min=-1, x_max=1),
            convert_point_to_graph_element('(-2, 5)', label='A'),
        ],
    })
    check(
        'GES1-10: normalized graph config preserves cosine and per-equation x-range',
        normalized['elements'][0]['family'] == 'cosine'
        and normalized['elements'][0]['x_min'] == -1.0
        and normalized['elements'][0]['x_max'] == 1.0
        and normalized['elements'][1]['element_type'] == 'point',
    )

    payload = _build_graph_plot_payload(normalized)
    trace = payload['data'][0]
    check(
        'GES1-11: plot payload respects per-equation x-range',
        round(trace['x'][0], 5) == -1.0 and round(trace['x'][-1], 5) == 1.0,
    )

    check(
        'GES1-12: incomplete or invalid equation x-range is rejected',
        _raises_value_error(convert_equation_to_graph_element, 'y = x', x_min=0, x_max=None)
        and _raises_value_error(convert_equation_to_graph_element, 'y = x', x_min=2, x_max=1),
    )


if __name__ == '__main__':
    print('\nGraph Equation Authoring Stage 1 - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL GRAPH EQUATION STAGE 1 TESTS PASSED.')
    else:
        print('SOME GRAPH EQUATION STAGE 1 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
