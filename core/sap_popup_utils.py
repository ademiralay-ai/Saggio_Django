def collect_popup_controls(wnd, normalize_id, iter_children):
    """Collect popup buttons, radios and input-like controls from a popup window."""
    buttons = []
    radios = []
    inputs = []
    btn_seen = set()
    rad_seen = set()
    inp_seen = set()

    stack = [wnd] if wnd is not None else []
    while stack:
        node = stack.pop(0)
        try:
            node_type_raw = str(getattr(node, "Type", "") or "")
            node_type = node_type_raw.casefold()
            node_id = normalize_id(str(getattr(node, "Id", "") or "").strip())

            if node_id:
                if ("button" in node_type or "/btn" in node_id.casefold()) and node_id not in btn_seen:
                    btn_seen.add(node_id)
                    btn_text = str(getattr(node, "Text", "") or "").strip()
                    btn_name = str(getattr(node, "Name", "") or "").strip()
                    btn_label = btn_text or btn_name or node_id or "Popup Butonu"
                    buttons.append({
                        "id": node_id,
                        "text": btn_text,
                        "name": btn_name,
                        "label": f"{btn_label} [{node_id}]",
                    })

                if ("radiobutton" in node_type or "/rad" in node_id.casefold()) and node_id not in rad_seen:
                    rad_seen.add(node_id)
                    rad_text = str(getattr(node, "Text", "") or "").strip()
                    rad_name = str(getattr(node, "Name", "") or "").strip()
                    rad_label = rad_text or rad_name or node_id or "Popup Radio"
                    radios.append({
                        "id": node_id,
                        "text": rad_text,
                        "name": rad_name,
                        "label": f"{rad_label} [{node_id}]",
                    })

                is_input_like = (
                    "/txt" in node_id.casefold()
                    or "/ctxt" in node_id.casefold()
                    or "textfield" in node_type
                    or "textbox" in node_type
                    or "inputfield" in node_type
                    or "passwordfield" in node_type
                )
                if is_input_like and node_id not in inp_seen:
                    inp_seen.add(node_id)
                    inp_text = str(getattr(node, "Text", "") or "").strip()
                    inp_name = str(getattr(node, "Name", "") or "").strip()
                    inp_label = inp_name or node_id or "Popup Input"
                    inputs.append({
                        "id": node_id,
                        "text": inp_text,
                        "name": inp_name,
                        "type": node_type_raw,
                        "label": f"{inp_label} [{node_id}]",
                    })
        except Exception:
            pass

        try:
            stack.extend(iter_children(node))
        except Exception:
            pass

    return buttons, radios, inputs


def select_popup_radio_by_id(radio_obj):
    """Try multiple strategies to select a popup radio control."""
    if radio_obj is None:
        return False, "radio nesnesi bos."

    errors = []
    try:
        radio_obj.select()
        return True, "select()"
    except Exception as ex:
        errors.append(f"select(): {ex}")

    try:
        radio_obj.selected = True
        return True, "selected=True"
    except Exception as ex:
        errors.append(f"selected=True: {ex}")

    try:
        radio_obj.setFocus()
        return True, "setFocus()"
    except Exception as ex:
        errors.append(f"setFocus(): {ex}")

    return False, " | ".join(errors)


def fill_popup_input_value(input_obj, value):
    """Try text/value assignment methods for popup input controls."""
    if input_obj is None:
        return False, "input nesnesi bos."

    val = str(value or "")
    errors = []

    try:
        input_obj.text = val
        return True, "text="
    except Exception as ex:
        errors.append(f"text=: {ex}")

    try:
        input_obj.Text = val
        return True, "Text="
    except Exception as ex:
        errors.append(f"Text=: {ex}")

    try:
        input_obj.value = val
        return True, "value="
    except Exception as ex:
        errors.append(f"value=: {ex}")

    try:
        input_obj.Value = val
        return True, "Value="
    except Exception as ex:
        errors.append(f"Value=: {ex}")

    return False, " | ".join(errors)
