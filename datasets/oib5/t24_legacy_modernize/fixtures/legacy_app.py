#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Legacy inventory management system (Python 2 style)"""

class InventoryItem:
    def __init__(self, name, price, quantity):
        self.name = name
        self.price = price
        self.quantity = quantity

    def __repr__(self):
        return "InventoryItem(%s, %s, %d)" % (self.name, self.price, self.quantity)

    def total_value(self):
        return self.price * self.quantity

    def is_low_stock(self, threshold=5):
        if self.quantity < threshold:
            return True
        else:
            return False


class Inventory:
    def __init__(self):
        self.items = {}

    def add_item(self, name, price, quantity):
        if self.items.has_key(name):
            self.items[name].quantity += quantity
        else:
            self.items[name] = InventoryItem(name, price, quantity)
        print "Added %d of %s" % (quantity, name)

    def remove_item(self, name, quantity):
        if not self.items.has_key(name):
            raise Exception, "Item not found: %s" % name
        item = self.items[name]
        if item.quantity < quantity:
            raise Exception, "Not enough stock for %s" % name
        item.quantity -= quantity
        if item.quantity == 0:
            del self.items[name]
        print "Removed %d of %s" % (quantity, name)

    def get_item(self, name):
        if self.items.has_key(name):
            return self.items[name]
        return None

    def total_value(self):
        total = 0
        for name, item in self.items.iteritems():
            total += item.total_value()
        return total

    def low_stock_items(self, threshold=5):
        result = []
        for name, item in self.items.iteritems():
            if item.is_low_stock(threshold):
                result.append(item)
        return result

    def search(self, query):
        results = filter(lambda item: query.lower() in item.name.lower(), self.items.values())
        return list(results)

    def apply_discount(self, name, percent):
        if not self.items.has_key(name):
            raise Exception, "Item not found"
        item = self.items[name]
        item.price = item.price * (100 - percent) / 100
        print "Applied %d%% discount to %s, new price: %s" % (percent, name, item.price)

    def generate_report(self):
        lines = []
        lines.append(u"=== Inventory Report ===")
        for name in sorted(self.items.keys()):
            item = self.items[name]
            lines.append(u"%s: $%.2f x %d = $%.2f" % (name, item.price, item.quantity, item.total_value()))
        lines.append(u"Total: $%.2f" % self.total_value())
        return u"\n".join(lines)


if __name__ == "__main__":
    inv = Inventory()
    inv.add_item("Widget", 9.99, 100)
    inv.add_item("Gadget", 24.99, 3)
    inv.add_item("Doohickey", 4.99, 50)
    print inv.generate_report()
    print "Low stock:", inv.low_stock_items()
