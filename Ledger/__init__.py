import sqlalchemy 
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql import text
import os
import time
import logging
import random
logging.basicConfig(
    level=logging.WARNING,
    format=f'%(asctime)s.%(msecs)03d - {os.getpid()} - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)


class Ledger:
    '''
    This class provides a python interface to the ledger database.
    Each method performs appropriate SQL commands to manipulate the database.
    '''

    def __init__(self, url):
        '''
        The constructor just creates a connection to the database.
        The same connection is re-used between all SQL commands,
        and the right way to think about a connection is as a single psql process where those commands will be entered.
        '''
        self.engine = sqlalchemy.create_engine(url)
        self.connection = self.engine.connect()

    def get_all_account_ids(self):
        '''
        This function is used inside of the random_transfers.py script.
        '''
        sql = text('SELECT account_id FROM accounts;')
        logging.debug(sql)
        results = self.connection.execute(sql)
        account_ids = [row[0] for row in results.all()]; self.connection.commit(); return account_ids

    def create_account(self, name):
        '''
        In order to create an account, we need to insert a new row into the "accounts" able and the "balances" table.
        Because of the FOREIGN KEY constraint on the "balances" table,
        we need to know the "account_id" column of the row we've inserted into "accounts".
        This value is generated for us automatically by the database, and not within python.
        So we need to query the database after inserting into "accounts" to get the value.
        '''
        with self.connection.begin():

            # insert the name into "accounts"
            sql = text('INSERT INTO accounts (name) VALUES (:name);')
            sql = sql.bindparams(name=name)
            logging.debug(sql)
            self.connection.execute(sql)

            # get the account_id for the new account
            sql = text('SELECT account_id FROM accounts WHERE name=:name')
            sql = sql.bindparams(name=name)
            logging.debug(sql)
            results = self.connection.execute(sql)
            account_id = results.first()[0]

            # add the row into the "balances" table
            sql = text('INSERT INTO balances VALUES (:account_id, 0);')
            sql = sql.bindparams(account_id=account_id)
            logging.debug(sql)
            self.connection.execute(sql)

    def transfer_funds(self, debit_account_id, credit_account_id, amount):

        while True:
            try:
                with self.connection.begin():

                    # Insert transaction
                    sql = text(
                        'INSERT INTO transactions '
                        '(debit_account_id, credit_account_id, amount) '
                        'VALUES (:debit_id, :credit_id, :amount);'
                    )
                    self.connection.execute(sql, {
                        'debit_id': debit_account_id,
                        'credit_id': credit_account_id,
                        'amount': amount
                    })

                    # Lock and read debit account
                    sql = text(
                        'SELECT balance FROM balances '
                        'WHERE account_id = :id FOR UPDATE;'
                    )
                    result = self.connection.execute(
                        sql, {'id': debit_account_id}
                    )
                    debit_balance = result.scalar_one()

                    # Update debit account
                    sql = text(
                        'UPDATE balances SET balance = :balance '
                        'WHERE account_id = :id;'
                    )
                    self.connection.execute(sql, {
                        'balance': debit_balance - amount,
                        'id': debit_account_id
                    })

                    # Lock and read credit account
                    sql = text(
                        'SELECT balance FROM balances '
                        'WHERE account_id = :id FOR UPDATE;'
                    )
                    result = self.connection.execute(
                        sql, {'id': credit_account_id}
                    )
                    credit_balance = result.scalar_one()

                    # Update credit account
                    sql = text(
                        'UPDATE balances SET balance = :balance '
                        'WHERE account_id = :id;'
                    )
                    self.connection.execute(sql, {
                        'balance': credit_balance + amount,
                        'id': credit_account_id
                    })

                # All operations succeeded and committed
                return

            except OperationalError as e:
                # PostgreSQL deadlock error code
                if getattr(e.orig, 'sqlstate', None) == '40P01':
                    logging.warning('Deadlock detected, retrying')
                    time.sleep(random.uniform(0.001, 0.01))
                    continue

                # Other database errors should not be ignored
                raise

