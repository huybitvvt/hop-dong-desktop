from __future__ import annotations

import shutil

from .customers import read_customers
from .storage import Store, resource_path


def bootstrap(store: Store):
    marker = store.directory / ".initialized"
    if marker.exists():
        return
    template = resource_path("Mau-thi-cong-minh-hoa.docx")
    customers = resource_path("Khach-hang-minh-hoa.xlsx")
    if template.exists():
        destination = store.templates / template.name
        if not destination.exists():
            shutil.copy2(template, destination)
    if customers.exists() and not store.customers():
        store.replace_customers(read_customers(customers))
        config = store.config()
        config.update(demo_data=True, customer_source="Danh sách minh họa đi kèm ứng dụng")
        config["seller"] = {"seller_company": "DOANH NGHIỆP MẪU (MINH HỌA)", "seller_tax_code": "DEMO-SELLER", "seller_address": "Địa chỉ công ty minh họa", "seller_representative": "Người đại diện minh họa", "seller_position": "Giám đốc"}
        store.save_config(config)
    marker.write_text("1", encoding="ascii")
