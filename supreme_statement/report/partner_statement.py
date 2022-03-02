import calendar
import datetime as dt
import calendar
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class PartnerStatement(models.TransientModel):
    _name = 'partner.statement'
    _description = 'Partner Statement'

    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company.id,
        string='Company'
    )

    date_start = fields.Date(required=True, string='Start Date')
    date_end = fields.Date(required=True, string='End Date')

    open_items = fields.Boolean(string='Open Items')

    partner_ids = fields.Many2many('res.partner', string='Partners')

    @api.model
    def default_get(self, fields):
        res = super(PartnerStatement, self).default_get(fields)

        active_ids = self.env.context.get('active_ids')
        if not active_ids:
            active_id = self.env.context.get('active_id')
            if active_id:
                active_ids = (active_id,)
        if self.env.context.get('active_model') == 'res.partner' and active_ids:
            today = dt.date.today()
            day = calendar.monthrange(today.year, today.month)[1]

            if 'partner_ids' in fields:
                res['partner_ids'] = [(6, 0, active_ids)]
            if 'date_start' in fields:
                res['date_start'] = dt.date(today.year, today.month, 1)
            if 'date_end' in fields:
                res['date_end'] = today.replace(day=day)
        return res

    def action_print(self):
        day = calendar.monthrange(self.date_end.year, self.date_end.month)[1]

        if self.date_end.day != day:
            self.date_end=self.date_end.replace(day=day)
        self.date_start=self.date_end.replace(day=1)

        return self.env.ref(
            'supreme_statement.action_report_partner_statement_balance')\
                .with_context(
                    date_start=self.date_end.replace(day=1), date_end=self.date_end.replace(day=day),
                    open_items=self.open_items)\
                .report_action(self.ids)

    def action_send(self):
        day = calendar.monthrange(self.date_end.year, self.date_end.month)[1]

        if self.date_end.day != day:
            self.date_end=self.date_end.replace(day=day)
        self.date_start=self.date_end.replace(day=1)

        template = self.env.ref(
            'supreme_statement.mail_template_partner_statement_balance')

        day = calendar.monthrange(self.date_end.year, self.date_end.month)[1]

        for partner in self.partner_ids:
            invoice_partner = self.env['res.partner'].browse(
                partner.address_get(['invoice'])['invoice'])
            email = invoice_partner.email
            if not email or not email.strip():
                raise UserError(_(
                    'Could not send mail to partner {} because it does not '
                    'have any email address defined').format(
                        partner.display_name))

            statement = self.copy({'partner_ids': [(6, 0, partner.ids)]})

            template.with_context(
                date_start=self.date_end.replace(day=1), date_end=self.date_end.replace(day=day),
                open_items=self.open_items,
            ).send_mail(statement.id, email_values={'email_to': email})

    def get_report_base_filename(self):
        if len(self.partner_ids) == 1:
            return _('Customer Statement - {}').format(
                self.partner_ids.commercial_company_name)
        else:
            return _('Customer Statements')

    def get_statement_lines(self, partner):
        self.ensure_one()
        day = calendar.monthrange(self.date_end.year, self.date_end.month)[1]
        if not self.date_end:
            today = dt.date.today()
            self.date_start = dt.date(today.year, today.month, 1)
            self.date_end = today.replace(day=day)

        commercial_partner = partner.commercial_partner_id or partner
        domain = [
            ('move_id.company_id', '=', self.env.company.id),
            ('move_id.partner_id', '=', partner.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.date', '>=', self.date_start),
            ('move_id.date', '<=', self.date_end),
            ('account_id.user_type_id.name', 'in', ['Payable', 'Receivable']),
        ]

        if partner.open_items:
            domain = [
                ('move_id.company_id', '=', self.env.company.id),
                ('move_id.partner_id', '=', partner.id),
                ('move_id.state', '=', 'posted'),
                ('move_id.date', '<=', self.date_end),
                ('account_id.user_type_id.name', 'in', ['Payable', 'Receivable']),
                ('move_id.amount_residual', '!=', 0.0)
            ]

        return self.env['account.move.line'].search(domain, order='date')

    def get_opening_balance(self, partner):
        day = calendar.monthrange(self.date_end.year, self.date_end.month)[1]
        if not self.date_end:
            today = dt.date.today()
            day = calendar.monthrange(self.date_end.year, self.date_end.month)[1]
            date_start = dt.date(today.year, today.month, 1)
            self.ate_end = today.replace(day=day)

        commercial_partner = partner.commercial_partner_id or partner

        args = [
            ('move_id.company_id', '=', self.env.company.id),
            ('move_id.partner_id', '=', partner.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.date', '<', self.date_end),
            ('account_id.user_type_id.name', 'in', ['Payable', 'Receivable']),
        ]

        lines = self.env['account.move.line'].search(args)

        return sum(lines.mapped('debit')) - sum(lines.mapped('credit'))

    def get_total_owing(self, partner):
        commercial_partner = partner.commercial_partner_id or partner

        args = [
            ('move_id.company_id', '=', self.env.company.id),
            ('move_id.partner_id', '=', partner.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.date', '<=', self.date_end),
            ('account_id.user_type_id.name', 'in', ['Payable', 'Receivable']),
        ]

        lines = self.env['account.move.line'].search(args)

        reconciled_credit_lines = lines.mapped('matched_credit_ids')
        reconciled_credit_lines = reconciled_credit_lines.filtered(
            lambda l: l.credit_move_id.date <= self.date_end)

        reconciled_debit_lines = lines.mapped('matched_debit_ids')
        reconciled_debit_lines = reconciled_debit_lines.filtered(
            lambda l: l.debit_move_id.date <= self.date_end)

        return sum(lines.mapped('balance')) - \
            sum(reconciled_credit_lines.mapped('amount')) + \
            sum(reconciled_debit_lines.mapped('amount'))

    def get_ageing_items(self, partner, start, end=0):
        commercial_partner = partner.commercial_partner_id or partner

        start_date = self.date_end - dt.timedelta(days=start)

        args = [
            ('move_id.company_id', '=', self.env.company.id),
            ('move_id.partner_id', '=', partner.id),
            ('move_id.state', '=', 'posted'),
            ('date', '<=', start_date),
            ('account_id.user_type_id.name', 'in', ['Payable', 'Receivable']),
        ]

        date_end = self.date_end - dt.timedelta(days=end)

        if end:
            args.append(('date', '>=', date_end))
        if partner.open_items:
            args.append(('amount_residual', '!=', 0.0))

        lines = self.env['account.move.line'].search(args)

        reconciled_credit_lines = lines.mapped('matched_credit_ids')
        reconciled_credit_lines = reconciled_credit_lines.filtered(
            lambda l: l.credit_move_id.date <= date_end)

        reconciled_debit_lines = lines.mapped('matched_debit_ids')
        reconciled_debit_lines = reconciled_debit_lines.filtered(
            lambda l: l.debit_move_id.date <= date_end)

        return sum(lines.mapped('move_id').mapped('amount_residual'))


    def get_ageing(self, partner, start, end=0):
        commercial_partner = partner.commercial_partner_id or partner

        start_date = self.date_end - dt.timedelta(days=start)

        args = [
            ('move_id.company_id', '=', self.env.company.id),
            ('move_id.partner_id', '=', partner.id),
            ('move_id.state', '=', 'posted'),
            ('date', '<=', start_date),
            ('account_id.user_type_id.name', 'in', ['Payable', 'Receivable']),
        ]

        date_end = self.date_end - dt.timedelta(days=end)

        if end:
            args.append(('date', '>=', date_end))


        lines = self.env['account.move.line'].search(args)

        reconciled_credit_lines = lines.mapped('matched_credit_ids')
        reconciled_credit_lines = reconciled_credit_lines.filtered(
            lambda l: l.credit_move_id.date <= date_end)

        reconciled_debit_lines = lines.mapped('matched_debit_ids')
        reconciled_debit_lines = reconciled_debit_lines.filtered(
            lambda l: l.debit_move_id.date <= date_end)

        return sum(lines.mapped('move_id').mapped('amount_residual'))


    def get_company(self):
        return self.env.company

    def get_user(self):
        return self.env.user

    def get_bank_foreign(self, partner):
        for bank in self.env.user.company_id.partner_id.bank_ids:
            if bank.bank_id.name == 'First National Bank - USD':
                return bank

    def get_bank(self, partner):
        for bank in self.env.user.company_id.partner_id.bank_ids:
            if bank.bank_id.name == 'First National Bank - Rands':
                return bank


    def get_date_end(self):
        day = calendar.monthrange(self.date_end.year, self.date_end.month)[1]
        date_start=self.date_end.replace(day=1)
        date_end=self.date_end.replace(day=day)
        if not self.date_end:
            today = dt.date.today()
            day = calendar.monthrange(self.date_end.year, self.date_end.month)[1]
            date_start = dt.date(today.year, today.month, 1)
            date_end = today.replace(day=day)

        return date_end


    def get_date_start(self):
        day = calendar.monthrange(self.date_end.year, self.date_end.month)[1]
        date_start=self.date_end.replace(day=1)
        date_end=self.date_end.replace(day=day)
        if not self.date_end:
            today = dt.date.today()
            day = calendar.monthrange(self.date_end.year, self.date_end.month)[1]
            date_start = dt.date(today.year, today.month, 1)
            date_end = today.replace(day=day)

        return date_start

    def get_credit(self, line):
        if line.credit != 0:
            return abs(line.amount_residual)
        else:
            return 0.00

    def get_debit(self, line):
        if line.debit != 0:
            return abs(line.amount_residual)
        else:
            return 0.00
