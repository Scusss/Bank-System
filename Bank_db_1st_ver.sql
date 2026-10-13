DROP DATABASE IF EXISTS bank;
CREATE DATABASE bank;
USE bank;


CREATE TABLE customer(
customer_id INT AUTO_INCREMENT PRIMARY KEY,
username VARCHAR(50) NOT NULL UNIQUE,
acc_password VARCHAR(255) NOT NULL,
first_name  VARCHAR(100) NOT NULL,
last_name VARCHAR(100) NOT NULL,
email VARCHAR(100) NOT NULL UNIQUE,
failed_attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,
is_locked BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE accounts(
account_id INT PRIMARY KEY AUTO_INCREMENT ,
account_number VARCHAR(20) UNIQUE NOT NULL,
customer_id INT NOT NULL,
balance DECIMAL (15,2) DEFAULT 0 NOT NULL,
FOREIGN KEY (customer_id)  References customer (customer_id),
CHECK (balance >= 0)
);

CREATE TABLE transaction_list(
transaction_id INT AUTO_INCREMENT PRIMARY KEY,
account_id INT NOT NULL,
amount DECIMAL(15,2) NOT NULL,
type_of_transaction enum('DEPOSIT','WITHDRAW') NOT NULL,
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
FOREIGN KEY (account_id)  References accounts (account_id)
);









-- test --
-- INSERT INTO customer(username,acc_password,first_name,last_name,email)
-- VALUES ('Aljhon','123456789','Aljhon','Arquiza','me@gmail.com');


-- INSERT INTO accounts(customer_id,account_number)
-- Values (1,'1000000001');


-- START TRANSACTION;
-- UPDATE accounts SET balance = balance + 500 WHERE account_id = 1;
-- INSERT INTO transaction_list (account_id, type_of_transaction, amount)
-- VALUES (1, 'DEPOSIT', 500.00);
-- COMMIT;


-- INSERT INTO customer(username,acc_password,first_name,last_name,email)
-- VALUES ('justin','987654321','justin','bieber','him@gmail.com');

-- INSERT INTO accounts(customer_id,account_number)
-- Values (2,'1000000002');

-- START TRANSACTION;
-- UPDATE accounts SET balance = balance + 500 WHERE account_id = 2;
-- INSERT INTO transaction_list (account_id, type_of_transaction, amount)
-- VALUES (2, 'DEPOSIT', 500.00);
-- COMMIT;

-- START TRANSACTION;
-- UPDATE accounts SET balance = balance -200 WHERE account_id = 2;
-- INSERT INTO transaction_list (account_id, type_of_transaction, amount)
-- VALUES (2, 'WITHDRAW', 200.00);
-- COMMIT;




-- SELECT * FROM transaction_list;-- 

-- SELECT c.first_name, a.account_number, a.balance
-- FROM customer c
-- JOIN accounts a ON a.customer_id = c.customer_id;

