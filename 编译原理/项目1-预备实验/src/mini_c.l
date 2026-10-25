%option noyywrap
%{
#include <stdio.h>
%}
%%
int|if|while           { printf("KW: %s\n", yytext); }
[A-Za-z_][A-Za-z_0-9]* { printf("ID: %s\n", yytext); }
[0-9]+                 { printf("INT: %s\n", yytext); }
[ \t\r\n]+             { /* skip whitespace */ }
.                      { printf("UNHANDLED: %s\n", yytext); }
%%
int main(void) { yylex(); return 0; }
