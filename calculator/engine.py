"""Reglas de P05, cuenta en dólares y partición temporal explícita."""

from decimal import Decimal, ROUND_FLOOR, localcontext
from .design import RULES


D = Decimal
INITIAL_CASH = D("10000")
STEP = D("0.00000001")
COMMISSION_RATE = D("0.0035")
MIN_COMMISSION = D("2")
VAT_RATE = D("0.21")
HALF_SPREAD = D("0.0002")
SLIPPAGE = D("0.0001")
WARMUP = 316
SMA_LENGTH = 200
IS_LENGTH = 176
OOS_LENGTH = 76
MIN_OOS = 30


def charges(notional):
    if notional == 0:
        return D(0), D(0)
    commission = max(MIN_COMMISSION, notional * COMMISSION_RATE)
    return commission, commission * VAT_RATE


def affordable_quantity(cash, price):
    # Se satisfacen simultáneamente los límites de comisión mínima y proporcional.
    with localcontext() as context:
        context.prec = 50
        notional = min(cash / (1 + COMMISSION_RATE * (1 + VAT_RATE)),
                       cash - MIN_COMMISSION * (1 + VAT_RATE))
        if notional <= 0:
            return D(0)
        quantity = (notional / price / STEP).to_integral_value(rounding=ROUND_FLOOR) * STEP
        while quantity > 0 and quantity * price + sum(charges(quantity * price)) > cash:
            quantity -= STEP
        return quantity


def prepare_prices(rows, rule="sma200"):
    family, length, threshold = RULES[rule]
    prices = [{"date": row["session_date"], "open": D(row["adj_open"]),
               "close": D(row["adj_close"])} for row in rows]
    signals = []
    with localcontext() as context:
        context.prec = 50
        for i, price in enumerate(prices):
            signal = {"mean": "", "sd": "", "reference": "", "value": "", "valid": False, "target": None}
            if family == "MOM" and i >= length:
                reference = prices[i - length]["close"]
                signal.update(reference=reference, value=price["close"] / reference - 1,
                              valid=True, target=int(price["close"] > reference))
            elif family != "MOM" and i >= length - 1:
                values = [p["close"] for p in prices[i + 1 - length:i + 1]]
                mean = sum(values, D(0)) / length
                signal["mean"] = mean
                if family == "P-SMA":
                    signal.update(value=mean, valid=True, target=int(price["close"] > mean))
                else:
                    variance = sum(((x - mean)**2 for x in values), D(0)) / length
                    sd = variance.sqrt()
                    signal["sd"] = sd
                    if sd:
                        # El cuadrado evita que el redondeo de la raíz cambie una igualdad con el umbral.
                        signal.update(value=(price["close"] - mean) / sd, valid=True,
                                      entry=price["close"] <= mean and (price["close"] - mean)**2 >= threshold**2 * variance,
                                      exit=price["close"] >= mean)
            signals.append(signal)
    return prices, signals


def make_windows(count, length_years=1):
    if length_years not in (1, 2, 3, 5, 7):
        raise ValueError("Longitud temporal fuera del diseño P05.")
    is_length = 252 * length_years * 70 // 100
    oos_length = 252 * length_years - is_length
    windows = []
    start = WARMUP
    while start + is_length < count:
        oos_start = start + is_length
        stop = min(count, oos_start + oos_length)
        windows.append({"window_id": f"w{len(windows) + 1:03d}", "number": len(windows) + 1,
                        "is_start": start, "is_stop": oos_start,
                        "oos_start": oos_start, "oos_stop": stop,
                        "oos_status": "evaluable" if stop - oos_start >= MIN_OOS else "insufficient_final_segment"})
        start += oos_length
    return windows


def simulate(prices, signals, calendar, start, stop, alternative, window_id,
             segment, execution_id, state=None, rule="sma200"):
    if alternative not in ("strategy", "buy_hold") or segment not in ("IS", "OOS") or rule not in RULES:
        raise ValueError("Regla, alternativa o tramo desconocido.")
    with localcontext() as context:
        context.prec = 50
        family = RULES[rule][0]
        cash, units = state if state is not None else (INITIAL_CASH, D(0))
        base = cash + units * prices[start - 1]["close"]
        previous = peak = base
        rows, orders = [], []
        for index in range(start - 1, stop):
            is_base = index == start - 1
            price = prices[index]
            quantity = D(0)
            commission = vat = spread_cost = slippage_cost = D(0)
            side = "none"
            mean = signal_date = signal_close = target = ""
            signal = {"sd": "", "reference": "", "value": "", "valid": ""}
            reason = "base" if is_base else "signal"
            if not is_base:
                signal = signals[index - 1]
                if not signal["valid"] and (family != "MR-Z" or signal["sd"] == ""):
                    raise ValueError("Señal sin historia suficiente.")
                mean, signal_date, signal_close = signal["mean"], prices[index - 1]["date"], prices[index - 1]["close"]
                if alternative == "buy_hold":
                    target = 1
                elif family == "MR-Z":
                    target = int(units > 0)
                    if signal["valid"]:
                        target = int(not signal["exit"]) if units else int(signal["entry"])
                    else:
                        reason = "undefined_z_keep_position"
                else:
                    target = signal["target"]
                if segment == "IS" and index == stop - 1:
                    target, reason = 0, "is_final_liquidation"
                if target == 1 and units == 0:
                    side = "buy"
                    execution_price = price["open"] * (1 + HALF_SPREAD + SLIPPAGE)
                    quantity = affordable_quantity(cash, execution_price)
                    if quantity == 0:
                        side, reason = "none", "insufficient_buy_cash"
                elif target == 0 and units > 0:
                    side = "sell"
                    execution_price = price["open"] * (1 - HALF_SPREAD - SLIPPAGE)
                    quantity = -units
                if quantity:
                    notional = abs(quantity) * execution_price
                    commission, vat = charges(notional)
                    next_cash = cash - quantity * execution_price - commission - vat
                    if next_cash < 0:
                        raise ValueError("El producido de la venta no cubre sus cargos; no se permite financiar el saldo.")
                    cash, units = next_cash, units + quantity
                    spread_cost = abs(quantity) * price["open"] * HALF_SPREAD
                    slippage_cost = abs(quantity) * price["open"] * SLIPPAGE
                    orders.append({"execution_id": execution_id, "window_id": window_id,
                                   "segment": segment, "alternative": alternative,
                                   "operation_id": f"{window_id}-{segment}-{alternative}-{index}",
                                   "session_date": price["date"], "executed_at": calendar[index]["open_at"],
                                   "signal_date": signal_date, "side": side, "reason": reason,
                                   "reference_open": price["open"], "execution_price": execution_price,
                                   "quantity": quantity, "notional": notional, "commission": commission,
                                   "vat": vat, "spread_cost": spread_cost, "slippage_cost": slippage_cost,
                                   "total_cost": commission + vat + spread_cost + slippage_cost,
                                   "cash_after": cash, "units_after": units})
            equity = cash + units * price["close"]
            if equity <= 0:
                raise ValueError("Patrimonio no positivo.")
            peak = max(peak, equity)
            rows.append({"execution_id": execution_id, "window_id": window_id,
                         "segment": segment, "alternative": alternative,
                         "session_date": price["date"], "observed_at": calendar[index]["close_at"],
                         "row_kind": "base" if is_base else "observation",
                         "signal_date": signal_date, "signal_close": signal_close, "sma_200": mean if rule == "sma200" else "",
                         "signal_mean": mean, "signal_sd": signal["sd"], "momentum_reference": signal["reference"],
                         "signal_value": signal["value"], "signal_valid": int(signal["valid"]) if not is_base else "",
                         "target_exposure": target, "operation": side, "operation_reason": reason,
                         "adjusted_open": "" if is_base else price["open"], "adjusted_close": price["close"],
                         "cash": cash, "units": units, "equity": equity,
                         "previous_equity": "" if is_base else previous,
                         "daily_return": "" if is_base else equity / previous - 1,
                         "normalized_equity": equity / base, "drawdown_signed": equity / peak - 1,
                         "commission": commission, "vat": vat, "spread_cost": spread_cost,
                         "slippage_cost": slippage_cost, "total_cost": commission + vat + spread_cost + slippage_cost})
            previous = equity
        return rows, orders, (cash, units)
