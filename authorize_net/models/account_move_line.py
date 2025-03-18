# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def reconcile(self):
        """
            Override method to set the group payment transactions in the invoices
        """
        res = super(AccountMoveLine, self).reconcile()
        line_ids = self._all_reconciled_lines().filtered(lambda l: l.matched_debit_ids or l.matched_credit_ids)
        payment_ids = line_ids.mapped('move_id.payment_id')
        for payment_id in payment_ids.filtered(lambda x: x.payment_token_id and x.payment_transaction_id):
            invoice_ids = payment_id.reconciled_invoice_ids
            invoice_ids.transaction_ids = [(4, payment_id.payment_transaction_id.id)]
        return res
