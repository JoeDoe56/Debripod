from datetime import datetime

from debripod.Services.indexers.cardigann.template import render_template


def test_simple_variables_functions_and_nested_logic():
    values = {"Query": {"Query": "Alice in Chains", "Categories": [1, 2]}, "Config": {"enabled": True, "mode": "music"}}
    assert render_template("q={{ .Query.Query }}", values) == "q=Alice in Chains"
    assert render_template('{{ re_replace .Query.Query " " "+" }}', values) == "Alice+in+Chains"
    assert render_template('{{ join .Query.Categories "," }}', values) == "1,2"
    template = '{{ if .Config.enabled }}{{ if eq .Config.mode "music" }}yes{{ else }}no{{ end }}{{ else }}off{{ end }}'
    assert render_template(template, values) == "yes"


def test_range_current_year_and_pipeline():
    values = {"Items": ["a", "b"], "Query": {"Query": "A B"}}
    assert render_template("{{ range .Items }}[{{ . }}]{{ end }}", values) == "[a][b]"
    assert render_template('{{ .Query.Query | re_replace " " "-" }}', values) == "A-B"
    assert render_template("{{ .CurrentYear }}", values) == str(datetime.now().year)


def test_parenthesized_nested_functions_match_prowlarr_templates():
    values = {"Keywords": "Alice", "False": False, "Config": {"disabled": False}, "Result": {"fallback": "kept"}}
    template = '{{ if and (.Keywords) (eq .Config.disabled .False) }}{{ or .Result.missing .Result.fallback }}{{ else }}off{{ end }}'
    assert render_template(template, values) == "kept"
    deeply_nested = '{{ if and (and (eq .Config.disabled .False) (ne .Result.fallback "missing")) (or .Keywords .Result.missing) }}nested{{ end }}'
    assert render_template(deeply_nested, values) == "nested"
