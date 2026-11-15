"""Customer-defined labels and safe flat Word variables; no global schema mutation."""
import hashlib
import re
from dataclasses import fields

from .models import Customer, FIELD_LABELS, UserError
from .money import normalize

CUSTOMER_BASE_FIELDS = tuple(item.name for item in fields(Customer) if item.name not in ("id", "extra_fields"))


def customer_field_key(label: str) -> str:
    label = str(label).strip()
    if not label or len(label) > 100:
        raise UserError("Tên trường khách hàng cần từ 1 đến 100 ký tự.")
    slug = re.sub(r"[^a-z0-9]+", "_", normalize(label)).strip("_")
    if not slug:
        slug = "truong_" + hashlib.sha256(label.encode()).hexdigest()[:12]
    if len(slug) > 60:
        slug = slug[:45].rstrip("_") + "_" + hashlib.sha256(label.encode()).hexdigest()[:10]
    return "customer_" + slug


def is_customer_field(name):
    return isinstance(name, str) and len(name) <= 80 and re.fullmatch(r"customer_[a-z0-9]+(?:_[a-z0-9]+)*", name) is not None


def clean_extra_fields(values: dict) -> dict[str, str]:
    if not isinstance(values, dict) or len(values) > 100:
        raise UserError("Mỗi khách hàng có thể có tối đa 100 trường bổ sung.")
    result, names = {}, set()
    for label, value in values.items():
        label = str(label).strip()
        name = customer_field_key(label)
        if name in names:
            raise UserError("Trùng tên trường khách hàng: " + label)
        if not isinstance(value, (str, int, float, type(None))):
            raise UserError("Giá trị trường khách hàng cần là văn bản: " + label)
        value = str(value).strip() if value is not None else ""
        if len(value) > 4000:
            raise UserError("Thông tin quá dài ở trường: " + label)
        result[label] = value
        names.add(name)
    return result


def merge_extra_fields(previous, incoming):
    result = clean_extra_fields(previous)
    by_key = {customer_field_key(label): label for label in result}
    for label, value in clean_extra_fields(incoming).items():
        target = by_key.get(customer_field_key(label), label)
        if value or target not in result:
            result[target] = value
        by_key[customer_field_key(label)] = target
    return clean_extra_fields(result)


def extra_field_labels(customers):
    result = {}
    for customer in customers:
        for label in customer.extra_fields:
            result.setdefault(customer_field_key(label), label)
    return result


def extra_context(customer):
    return {customer_field_key(label): value for label, value in clean_extra_fields(customer.extra_fields).items()}


def field_label(name, labels=None):
    if labels and name in labels:
        return labels[name]
    if name in FIELD_LABELS:
        return FIELD_LABELS[name]
    if is_customer_field(name):
        return name.removeprefix("customer_").replace("_", " ").capitalize()
    return {"day": "Ngày", "month": "Tháng", "year": "Năm"}.get(name, name)


def explicit_customer_values(prompt, labels):
    lookup = {normalize(label): key for key, label in labels.items() if is_customer_field(key)}
    result = {}
    for line in prompt.splitlines():
        label, separator, value = line.partition(":")
        key = lookup.get(normalize(label))
        if separator and key and value.strip():
            value = value.strip()
            if key in result and result[key] != value:
                raise UserError("Yêu cầu có hai giá trị khác nhau cho " + labels[key] + ". Hãy chỉ ghi một giá trị.")
            result[key] = value
    return result
