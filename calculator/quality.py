"""Controles de integridad y cobertura; no simula estrategias."""

from collections import Counter
from datetime import date, datetime
from math import isclose, isfinite


INSTRUMENTS = {"SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"}
WARMUP_SESSIONS = 316


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(rows, keys, label):
    values = [tuple(row[key] for key in keys) for row in rows]
    require(len(values) == len(set(values)), f"Claves duplicadas en {label}.")


def number(value):
    result = float(value)
    require(isfinite(result), "Se encontró un número no finito.")
    return result


def inspect_tables(manifest, tables):
    checks = [{"check": "Huellas y filas del manifiesto", "status": "Conforme"}]
    instruments, calendar, prices, rates, trace = (
        tables[name] for name in ("instruments", "calendar", "prices", "rates", "rate-trace")
    )
    for rows, keys, name in (
        (instruments, ["instrument_id"], "instrumentos"),
        (calendar, ["session_date"], "calendario"),
        (prices, ["instrument_id", "session_date"], "precios"),
        (rates, ["rate_id"], "tasas"),
        (trace, ["session_date"], "alineación de tasas"),
        (tables["dictionary"], ["table", "field"], "diccionario"),
    ):
        unique(rows, keys, name)
    ids = {row["instrument_id"] for row in instruments}
    require(ids == INSTRUMENTS, "El universo debe contener los siete ETF definidos.")
    require(all(row["currency"] == "USD" for row in instruments), "Moneda inesperada.")
    checks.append({"check": "Claves únicas y universo", "status": "Conforme"})

    dates = [row["session_date"] for row in calendar]
    require(len(dates) > WARMUP_SESSIONS and dates == sorted(dates), "Calendario insuficiente o desordenado.")
    for index, row in enumerate(calendar):
        day = date.fromisoformat(row["session_date"])
        require(2016 <= day.year <= 2025, "Fecha fuera del período definido.")
        require(int(row["session_number"]) == index + 1, "Número de sesión discontinuo.")
        require(row["previous_session_date"] == (dates[index - 1] if index else ""), "Sesión previa incorrecta.")
        require(row["next_session_date"] == (dates[index + 1] if index + 1 < len(dates) else ""), "Sesión siguiente incorrecta.")
        opened, closed = (datetime.fromisoformat(row[key]) for key in ("open_at", "close_at"))
        require(opened.tzinfo is not None and closed.tzinfo is not None and opened < closed, "Horario de sesión inválido.")
        require(opened.date() == day and closed.date() == day, "Horario fuera de su sesión.")
    expected_dates = set(dates)
    coverage = []
    for instrument in sorted(ids):
        rows = [row for row in prices if row["instrument_id"] == instrument]
        found = {row["session_date"] for row in rows}
        require(found == expected_dates, f"Cobertura incompleta o fechas adicionales: {instrument}.")
        require([row["session_date"] for row in rows] == dates, f"Precios desordenados: {instrument}.")
        coverage.append({"instrument_id": instrument, "observations": len(rows), "first_date": min(found),
                         "last_date": max(found), "missing_sessions": 0, "coverage": len(found) / len(dates)})
    require(len(prices) == len(dates) * len(ids), "Precios de instrumentos no declarados.")
    for row in prices:
        values = {key: number(value) for key, value in row.items() if key not in ("instrument_id", "session_date")}
        require(all(values[key] > 0 for key in ("open", "high", "low", "close", "adj_close", "adjustment_factor")), "Precio no positivo.")
        require(values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"], "Rango OHLC inválido.")
        require(values["volume"] >= 0 and values["volume"].is_integer(), "Volumen inválido.")
        require(all(values[key] >= 0 for key in ("dividends", "stock_splits", "capital_gains")), "Evento corporativo negativo.")
        factor = values["adj_close"] / values["close"]
        require(isclose(factor, values["adjustment_factor"], rel_tol=1e-12), "Factor de ajuste inconsistente.")
        for key in ("open", "high", "low"):
            require(isclose(values[key] * factor, values[f"adj_{key}"], rel_tol=1e-12), "Precio ajustado inconsistente.")
    checks.extend([{"check": "Cobertura respecto del calendario conservado", "status": "Conforme"},
                   {"check": "Precios, eventos y ajustes", "status": "Conforme"}])

    parsed_rates = []
    missing_source = 0
    for row in rates:
        require(row["series_id"] == "DGS3MO", "Serie de referencia inesperada.")
        observed = date.fromisoformat(row["observation_date"])
        available = datetime.fromisoformat(row["available_at"])
        until = datetime.fromisoformat(row["valid_until"]) if row["valid_until"] else None
        require(available.tzinfo is not None and (until is None or until.tzinfo is not None), "Tasa sin zona horaria.")
        require(observed <= available.date() and (until is None or available < until), "Vigencia de tasa inválida.")
        if row["quoted_value"]:
            number(row["quoted_value"])
        else:
            missing_source += 1
            require(row["status"] == "source_missing", "Ausencia de tasa sin estado explícito.")
        parsed_rates.append((row, observed, available, until))
    require([row["session_date"] for row in trace] == dates, "La alineación no coincide con el calendario.")
    unavailable = []
    for index, row in enumerate(trace):
        if not index:
            require(not row["rate_id"] and not row["decision_at"], "La primera sesión no tiene cierre previo en el recorte.")
            eligible = []
        else:
            expected = datetime.fromisoformat(calendar[index - 1]["close_at"])
            require(datetime.fromisoformat(row["decision_at"]) == expected, "La tasa no usa el cierre anterior.")
            eligible = [item for item in parsed_rates if item[0]["quoted_value"]
                        and item[1] <= expected.date() and item[2] <= expected
                        and (item[3] is None or expected < item[3])]
        if eligible:
            selected = max(eligible, key=lambda item: (item[1], item[2]))[0]
            require(row["rate_id"] == selected["rate_id"] and row["status"] == "available_under_policy", "Tasa elegida distinta de la última elegible.")
        else:
            require(not row["rate_id"] and row["status"] == "not_available", "Tasa inexistente presentada como disponible.")
            unavailable.append(index)
    require(not any(index >= WARMUP_SESSIONS for index in unavailable), "Falta tasa elegible después del calentamiento.")
    checks.append({"check": "Tasas y alineación temporal registrada", "status": "Conforme"})
    annual = Counter(row["session_date"][:4] for row in calendar)
    return {
        "summary": [{"dataset_id": manifest["dataset_id"], "dataset_state": manifest["state"],
                     "instruments": len(ids), "price_rows": len(prices), "sessions": len(dates),
                     "first_date": dates[0], "last_date": dates[-1], "rate_rows": len(rates),
                     "missing_source_rates": missing_source, "unavailable_rate_sessions": len(unavailable),
                     "unavailable_rates_after_warmup": 0, "sessions_after_warmup": len(dates) - WARMUP_SESSIONS}],
        "coverage": coverage,
        "annual": [{"year": int(year), "sessions": count} for year, count in sorted(annual.items())],
        "checks": checks,
    }
