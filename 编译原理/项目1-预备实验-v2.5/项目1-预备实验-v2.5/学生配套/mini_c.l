%option noyywrap
%{
#include <stdio.h>
%}
%%
[ \t\r\n]+ { /* skip whitespace */ }
.           { printf("UNHANDLED: %s\n", yytext); }
%%
int main(void) { yylex(); return 0; }
